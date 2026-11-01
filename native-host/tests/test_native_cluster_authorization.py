#!/usr/bin/env python3
"""Real cluster Handler/SQLite + C++ backend tests; hostile HTTP tests are separate.

No production profile, password verifier, renderer, supervisor or camera is used.
"""
from __future__ import annotations

import argparse
import contextlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import queue
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("native_auth_cluster_fixture", ROOT / "cluster/cluster_service.py")
cluster = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cluster
SPEC.loader.exec_module(cluster)
PROBE = None


class FixtureHasher:
    # Password verification/Argon2 is not under test; no real credential is used.
    def hash(self, _password):
        return "fixture-only-not-a-password-hash"


class QuietCluster(cluster.Handler):
    def log_message(self, *_args):
        pass


@contextlib.contextmanager
def serving(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        if thread.is_alive():
            raise AssertionError("owned fixture server did not stop")


class Probe:
    def __init__(self, root, port, token, *, connect=100, total=500, env=None):
        self.path = root / (secrets.token_hex(8) + ".sqlite3")
        self.process = subprocess.Popen([str(PROBE), str(self.path), str(port)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=env)
        self.token = token
        self.responses = queue.Queue()

        def read_responses():
            while True:
                line = self.process.stdout.readline(128)
                self.responses.put(line)
                if not line:
                    return

        self.reader = threading.Thread(target=read_responses, daemon=True)
        self.reader.start()
        try:
            self.init_status = self.call(op="init", token=token, connectMs=connect, totalMs=total)
        except BaseException:
            self.close()
            raise

    def call(self, **value):
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()
        try:
            line = self.responses.get(timeout=3)
        except queue.Empty:
            self.process.kill()
            self.process.wait(timeout=5)
            raise AssertionError("owned probe exceeded its response deadline") from None
        if not line or len(line) > 16 or (len(self.token) == 64 and self.token in line):
            raise AssertionError("probe failed or disclosed an internal credential")
        return int(line)

    def create(self, user="viewer-one", slot="a"):
        if self.call(op="create", user=user, slot=slot) != 200:
            raise AssertionError("fixture session creation failed")

    def auth(self, slot="a", command=2, camera="camera-a"):
        return self.call(op="authorize", slot=slot, command=command, camera=camera)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            raise AssertionError("owned probe exceeded its shutdown bound")
        self.reader.join(timeout=2)
        if self.reader.is_alive():
            raise AssertionError("owned probe response reader did not stop")
        error = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        if self.process.returncode != 0 or error:
            raise AssertionError("native account probe failed")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class NativeAccountTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="webobs-native-cluster-test-")
        self.root = Path(self.directory.name)
        self.token = secrets.token_hex(32)

    def tearDown(self):
        self.directory.cleanup()

    @contextlib.contextmanager
    def real_cluster(self):
        registry = self.root / "registry.sqlite3"
        with contextlib.closing(sqlite3.connect(registry)) as db, db:
            db.execute("CREATE TABLE cameras(id TEXT PRIMARY KEY,group_id TEXT NOT NULL)")
            db.executemany("INSERT INTO cameras VALUES(?,?)", [("camera-a", "group-a"), ("camera-b", "group-b")])
        store = cluster.ClusterStore(self.root / "accounts.sqlite3", FixtureHasher(),
            secrets_root=self.root / "secrets", camera_registry_path=registry)
        try:
            for user, roles, scopes in [
                ("admin-one", ["admin"], []),
                ("viewer-one", ["viewer"], [{"kind": "camera", "id": "camera-a"}]),
                ("group-one", ["viewer"], [{"kind": "group", "id": "group-a"}]),
                ("empty-one", ["viewer"], []),
            ]:
                store.create_user({"username": user, "password": "fixture-password-not-used",
                                   "roles": roles, "scopes": scopes})
            with mock.patch.object(cluster, "STORE", store), mock.patch.object(cluster, "INTERNAL_TOKEN", self.token):
                with serving(QuietCluster) as server:
                    yield store, registry, server.server_port
        finally:
            store.close()

    def test_owned_fixture_database_handles_close_without_garbage_collection(self):
        connections = []
        original_connect = sqlite3.connect

        class TrackedConnection(sqlite3.Connection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.explicitly_closed = False
                connections.append(self)

            def close(self):
                super().close()
                self.explicitly_closed = True

        def connect(*args, **kwargs):
            return original_connect(*args, **kwargs, factory=TrackedConnection)

        # Keeping strong references deliberately prevents GC from hiding a
        # leaked handle on POSIX, where unlink would otherwise still succeed.
        with mock.patch.object(sqlite3, "connect", side_effect=connect):
            with self.real_cluster() as (_store, _registry, port), Probe(self.root, port, self.token) as probe:
                probe.create()
                self.assertEqual(probe.auth(), 200)
            good = json.dumps({"allowed": True, "userId": "a" * 32, "permission": "live.view"}).encode()
            self.assertEqual(self.hostile(body=good)[0], 200)
        self.assertGreaterEqual(len(connections), 4)
        self.assertTrue(all(connection.explicitly_closed for connection in connections))

    def test_real_cluster_fresh_roles_camera_scopes_and_group_registry(self):
        with self.real_cluster() as (store, registry, port), Probe(self.root, port, self.token) as probe:
            self.assertEqual(probe.init_status, 200)
            probe.create()
            self.assertEqual(probe.auth(), 200)
            self.assertEqual(probe.auth(camera="camera-b"), 403)
            self.assertEqual(probe.auth(command=1), 403)
            # Real store update: the same persistent session sees the new role.
            user = next(item for item in store.list_users()["users"] if item["username"] == "viewer-one")
            store.update_user(user["id"], {"roles": ["admin"]}, user["revision"])
            self.assertEqual(probe.auth(command=1), 200)
            user = next(item for item in store.list_users()["users"] if item["username"] == "viewer-one")
            store.update_user(user["id"], {"roles": ["viewer"]}, user["revision"])
            self.assertEqual(probe.auth(command=1), 403)
            user = next(item for item in store.list_users()["users"] if item["username"] == "viewer-one")
            store.update_user(user["id"], {"scopes": [{"kind": "camera", "id": "camera-b"}]}, user["revision"])
            self.assertEqual(probe.auth(), 403)
            self.assertEqual(probe.auth(camera="camera-b"), 200)
            probe.create("group-one", "group")
            self.assertEqual(probe.auth("group"), 200)
            with contextlib.closing(sqlite3.connect(registry)) as db, db:
                db.execute("UPDATE cameras SET group_id='group-b' WHERE id='camera-a'")
            self.assertEqual(probe.auth("group"), 403)
            probe.create("empty-one", "empty")
            self.assertEqual(probe.auth("empty"), 403)
            # This coarse permission is deliberately NOT an all-camera grant.
            self.assertEqual(probe.auth("empty", command=0, camera=""), 200)

    def test_real_disabled_user_revokes_all_local_sessions_not_other_accounts(self):
        with self.real_cluster() as (store, _registry, port), Probe(self.root, port, self.token) as probe:
            probe.create()
            probe.create(slot="second")
            probe.create("admin-one", "admin")
            user = next(item for item in store.list_users()["users"] if item["username"] == "viewer-one")
            store.update_user(user["id"], {"enabled": False}, user["revision"])
            self.assertEqual(probe.auth(), 401)
            self.assertEqual(probe.auth("second"), 401)
            self.assertEqual(probe.auth("admin", command=1), 200)
            with contextlib.closing(sqlite3.connect(probe.path)) as db, db:
                rows = db.execute("SELECT user_name FROM auth_sessions").fetchall()
            self.assertEqual(rows, [("admin-one",)])

    def test_real_wrong_service_token_is_outage_and_preserves_session(self):
        with self.real_cluster() as (_store, _registry, port), Probe(self.root, port, "b" * 64) as probe:
            probe.create()
            self.assertEqual(probe.auth(), 503)
            self.assertEqual(probe.call(op="init", token=self.token, connectMs=100, totalMs=500), 200)
            self.assertEqual(probe.auth(), 200)

    def hostile(self, *, body=b"", status=200, headers=(), delay=0, env=None, token=None, connect=100, total=500, direct=None):
        observed = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                observed.append((self.path, dict(self.headers), json.loads(raw)))
                if delay:
                    time.sleep(delay)
                try:
                    self.send_response(status)
                    for key, value in headers:
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (ConnectionError, OSError):
                    pass

        with serving(Handler) as server, Probe(self.root, server.server_port,
                self.token if token is None else token, connect=connect, total=total, env=env) as probe:
            probe.create()
            started = time.monotonic()
            reply = probe.auth() if direct is None else probe.call(op="direct", **direct)
            elapsed = time.monotonic() - started
            with contextlib.closing(sqlite3.connect(probe.path)) as db, db:
                remaining = db.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0]
            self.assertEqual(remaining, 0 if reply == 401 and direct is None else 1)
            return reply, observed, elapsed, probe.init_status

    def test_hostile_200_is_not_a_status_only_grant(self):
        valid = {"allowed": True, "userId": "a" * 32, "permission": "live.view"}
        bad = [b"", b"null", b"[]", b"{", b"{}", b"true", b"x" * 4097,
            b'{"allowed":true,"allowed":false,"userId":"' + b"a" * 32 + b'","permission":"live.view"}',
            json.dumps(valid).encode() + b" trailing",
            json.dumps(valid).encode() + b"\x00",
        ]
        for key, values in {"allowed": [False, 1, "true"], "userId": ["", "a" * 31, "A" * 32, "a" * 32 + "\x00"],
                            "permission": ["scene.write", "live.view\x00"]}.items():
            bad.extend(json.dumps({**valid, key: value}).encode() for value in values)
        bad.append(json.dumps({**valid, "unexpected": "extra"}).encode())
        for body in bad:
            with self.subTest(case=bad.index(body)):
                self.assertEqual(self.hostile(body=body)[0], 503)
        reply, observed, _, _ = self.hostile(body=json.dumps(valid).encode())
        self.assertEqual(reply, 200)
        path, headers, request = observed[0]
        self.assertEqual(path, "/auth/authorize")
        self.assertEqual(request, {"username": "viewer-one", "permission": "live.view", "cameraId": "camera-a"})
        self.assertEqual(headers["X-WebObs-Internal-Admin"], self.token)
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("Authorization", headers)

    def test_only_recognized_backend_errors_change_auth_state(self):
        cases = [(403, "permission_rejected", 403), (404, "user_not_found", 401),
                 (403, "internal_auth_rejected", 503), (404, "not_found", 503),
                 (500, "internal_error", 503), (200, "permission_rejected", 503),
                 (404, "permission_rejected", 503), (401, "user_not_found", 503)]
        for status, code, expected in cases:
            with self.subTest(status=status, code=code):
                message = {"permission_rejected": "permission or resource scope was rejected",
                           "user_not_found": "user is not managed by RBAC"}.get(code, "fixture failure")
                body = json.dumps({"error": {"code": code, "message": message}}).encode()
                self.assertEqual(self.hostile(body=body, status=status)[0], expected)
        for status in (403, 404):
            self.assertEqual(self.hostile(body=b"{}", status=status)[0], 503)

    def test_header_overflow_and_deadline_fail_closed(self):
        good = json.dumps({"allowed": True, "userId": "a" * 32, "permission": "live.view"}).encode()
        self.assertEqual(self.hostile(body=good, headers=[("X-Fixture", "x" * 17000)])[0], 503)
        self.assertEqual(self.hostile(body=good, headers=[("X-Fixture", "x")] * 130)[0], 503)
        reply, _, elapsed, _ = self.hostile(body=good, delay=0.6, total=100, connect=50)
        self.assertEqual(reply, 503)
        self.assertLess(elapsed, 2.0)

    def test_no_redirect_and_no_environment_proxy_can_receive_service_token(self):
        trap_requests = []

        class Trap(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                trap_requests.append(True)
                self.send_response(500)
                self.end_headers()
            do_GET = do_POST

        good = json.dumps({"allowed": True, "userId": "a" * 32, "permission": "live.view"}).encode()
        with serving(Trap) as trap:
            target = f"http://127.0.0.1:{trap.server_port}/trap"
            env = {**os.environ, "http_proxy": target, "HTTP_PROXY": target,
                   "ALL_PROXY": target, "all_proxy": target, "no_proxy": "", "NO_PROXY": ""}
            self.assertEqual(self.hostile(body=good, env=env)[0], 200)
            self.assertEqual(self.hostile(body=good, status=307, headers=[("Location", target)])[0], 503)
        self.assertEqual(trap_requests, [])

    def test_unconfigured_and_invalid_direct_requests_do_not_contact_backend(self):
        for token, connect, total in [("", 100, 500), ("A" * 64, 100, 500), ("a" * 63 + "\n", 100, 500),
                                       (self.token, 0, 500), (self.token, 501, 1000), (self.token, 100, 2001)]:
            with self.subTest(case=(len(token), connect, total)):
                reply, observed, _, configured = self.hostile(token=token, connect=connect, total=total)
                self.assertEqual((reply, observed, configured), (503, [], 503))
        # Closed loopback port: no retry, no fallback, fixed unavailable decision.
        with serving(QuietCluster) as server:
            port = server.server_port
        with Probe(self.root, port, self.token) as probe:
            probe.create()
            self.assertEqual(probe.auth(), 503)
        for user, permission, camera in [("x", "live.view", "camera-a"), ("viewer-one", "*", "camera-a"),
                ("viewer-one", "live.view", ""), ("viewer-one", "live.view", "camera-a\r\n"),
                ("viewer-one\x00", "scene.read", ""), ("v" * 65, "live.view", "camera-a"),
                ("viewer-one", "live.view", "a" * 65), ("viewer-one", "live.view", "camera/a")]:
            reply, observed, _, _ = self.hostile(direct={"user": user, "permission": permission, "camera": camera})
            self.assertEqual((reply, observed), (503, []))
        good = json.dumps({"allowed": True, "userId": "a" * 32, "permission": "live.view"}).encode()
        reply, observed, _, _ = self.hostile(body=good, direct={"user": "viewer-one", "permission": "live.view", "camera": "camera-a"})
        self.assertEqual((reply, len(observed)), (200, 1))
        with Probe(self.root, 0, self.token) as probe:
            self.assertEqual(probe.init_status, 503)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    PROBE = args.probe.resolve(strict=True)
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
