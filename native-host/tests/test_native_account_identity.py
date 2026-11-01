#!/usr/bin/env python3
"""Synthetic native identity protocol tests, with private SQLite and no listener.

The fixture hasher deliberately does not exercise Argon2, production credentials,
profiles, C++ session storage, camera streams or execution-time fencing.
"""
from __future__ import annotations

import contextlib
from email.message import Message
import importlib.util
import io
import itertools
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("native_identity_cluster_fixture", ROOT / "cluster/cluster_service.py")
cluster = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cluster
SPEC.loader.exec_module(cluster)

# Fixed synthetic fixture values only; never log credentials or identity guards.
PASSWORD = "synthetic-fixture-password"
TOKEN = "synthetic-internal-admin"
HASH = "fixture-only-not-an-argon2-hash"


class FixtureHasher:
    """Protocol-only verifier; this is explicitly not an Argon2 test."""

    def hash(self, password):
        if not isinstance(password, str):
            raise cluster.ApiError(400, "invalid_password", "password must be a string")
        return HASH

    def verify(self, encoded, password):
        return encoded == HASH and password == PASSWORD


class NativeAccountIdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="webobs-native-identity-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        counter = itertools.count(100)

        def fixed_hex(size):
            # The product still calls secrets.token_hex(16); only the isolated
            # fixture substitutes deterministic, valid, unique random outputs.
            if size != 16:
                raise AssertionError("unexpected fixture random width")
            return format(next(counter), "032x")

        patcher = mock.patch.object(cluster.secrets, "token_hex", side_effect=fixed_hex)
        self.random_hex = patcher.start()
        self.addCleanup(patcher.stop)
        self.registry = self.root / "registry.sqlite3"
        with contextlib.closing(sqlite3.connect(self.registry)) as db, db:
            db.execute("CREATE TABLE cameras(id TEXT PRIMARY KEY,group_id TEXT NOT NULL)")
            db.executemany("INSERT INTO cameras VALUES(?,?)", [("camera-a", "group-a"), ("camera-b", "group-b")])
        self.store = self.new_store(self.root / "accounts.sqlite3")
        self.addCleanup(self.store.close)

    def new_store(self, path):
        return cluster.ClusterStore(path, FixtureHasher(), secrets_root=self.root / "secrets",
                                    camera_registry_path=self.registry)

    def create(self, username="viewer-one", roles=None, scopes=None):
        return self.store.create_user({"username": username, "password": PASSWORD,
                                      "roles": roles or ["viewer"], "scopes": scopes or []})

    def login(self, username="viewer-one"):
        return self.store.native_login({"username": username, "password": PASSWORD, "clientKey": "fixture-client"})

    @staticmethod
    def authorization(identity, permission="live.view", camera=""):
        return {"username": identity["username"], "userId": identity["userId"],
                "authEpoch": identity["authEpoch"], "permission": permission, "cameraId": camera}

    def update(self, identity, patch):
        row = self.store.db.execute("SELECT revision FROM users WHERE id=?", (identity["userId"],)).fetchone()
        return self.store.update_user(identity["userId"], patch, row["revision"])

    def assert_api_error(self, status, operation, code=None, message=None):
        with self.assertRaises(cluster.ApiError) as caught:
            operation()
        self.assertEqual(caught.exception.status, status)
        if code is not None:
            self.assertEqual(caught.exception.code, code)
        if message is not None:
            self.assertEqual(caught.exception.message, message)

    def assert_stale(self, identity):
        self.assert_api_error(404, lambda: self.store.native_authorize(self.authorization(identity)),
                              "user_not_found", "user is not managed by RBAC")

    def request(self, path, value, *, token=TOKEN, method="POST", raw=None):
        """Run the actual HTTP dispatch/read_json/admin chain without sockets."""
        body = json.dumps(value).encode() if raw is None else raw
        handler = cluster.Handler.__new__(cluster.Handler)
        handler.command = method
        handler.path = path
        handler.headers = Message()
        handler.headers["Content-Type"] = "application/json"
        handler.headers["Content-Length"] = str(len(body))
        if token is not None:
            handler.headers["X-WebObs-Internal-Admin"] = token
        handler.rfile = io.BytesIO(body)
        responses = []
        handler.response = lambda status, value=None: responses.append((status, value))
        with mock.patch.object(cluster, "STORE", self.store), mock.patch.object(cluster, "INTERNAL_TOKEN", TOKEN):
            handler.dispatch()
        self.assertEqual(len(responses), 1)
        return responses[0]

    def test_old_schema_migration_is_per_row_nullable_atomic_and_restart_idempotent(self):
        path = self.root / "legacy.sqlite3"
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,"
                       "password_hash TEXT NOT NULL,enabled INTEGER NOT NULL,created_at INTEGER NOT NULL,"
                       "updated_at INTEGER NOT NULL,revision INTEGER NOT NULL)")
            db.executemany("INSERT INTO users VALUES(?,?,?,?,?,?,?)", [
                ("1" * 32, "legacy-one", HASH, 1, 1, 1, 1),
                ("2" * 32, "legacy-two", HASH, 0, 1, 1, 1),
            ])
        with contextlib.closing(self.new_store(path)) as store:
            epochs = dict(store.db.execute("SELECT id,auth_epoch FROM users"))
            self.assertTrue(all(cluster.ClusterStore._valid_native_guard(item) for item in epochs.values()))
            self.assertEqual(len(set(epochs.values())), 2)
            column = next(row for row in store.db.execute("PRAGMA table_info(users)") if row[1] == "auth_epoch")
            self.assertEqual(column[2:5], ("TEXT", 0, None))
            self.assertFalse(store.db.in_transaction)
        calls = self.random_hex.call_count
        with contextlib.closing(self.new_store(path)) as store:
            self.assertTrue(dict(store.db.execute("SELECT id,auth_epoch FROM users")) == epochs,
                            "restart changed account guards")
            self.assertEqual(self.random_hex.call_count, calls)
            # Explicit eight-column INSERT also works against the upgraded table.
            user = store.create_user({"username": "created-after-upgrade", "password": PASSWORD, "roles": ["viewer"]})
            identity = store.native_login({"username": user["username"], "password": PASSWORD, "clientKey": "fixture"})
            self.assertTrue(store._valid_native_guard(identity["authEpoch"]))

    def test_existing_corrupt_guards_are_never_repaired_or_granted(self):
        user = self.create()
        for corrupt in (None, "", "A" * 32, "not-a-guard"):
            with self.store.lock, self.store.db:
                self.store.db.execute("UPDATE users SET auth_epoch=? WHERE id=?", (corrupt, user["id"]))
            with contextlib.closing(self.new_store(self.store.path)) as reopened:
                row = reopened.db.execute("SELECT auth_epoch FROM users WHERE id=?", (user["id"],)).fetchone()
                self.assertTrue(row[0] == corrupt, "corrupt guard was silently repaired")
                self.assert_api_error(503, lambda: reopened.native_login(
                    {"username": user["username"], "password": PASSWORD, "clientKey": "fixture"}))
                self.assert_api_error(404, lambda: reopened.native_authorize({"username": user["username"],
                    "userId": user["id"], "authEpoch": "f" * 32, "permission": "live.view", "cameraId": ""}))

    def test_first_admin_and_new_users_get_valid_identity_without_public_guard_leak(self):
        user = self.store.register_first_admin({"username": "admin-one", "password": PASSWORD})
        self.assertNotIn("authEpoch", user)
        identity = self.login("admin-one")
        self.assertEqual(set(identity), {"userId", "username", "authEpoch"})
        self.assertTrue(identity["userId"] == user["id"], "login changed user identity")
        self.assertTrue(all(self.store._valid_native_guard(identity[key]) for key in ("userId", "authEpoch")))
        result = self.store.native_authorize(self.authorization(identity, "settings.manage"))
        self.assertTrue(result == {"allowed": True, "userId": identity["userId"],
            "authEpoch": identity["authEpoch"], "permission": "settings.manage"}, "authorization body mismatch")
        self.assertTrue(all("authEpoch" not in item for item in self.store.list_users()["users"]))

    def test_same_password_reset_and_self_change_each_rotate(self):
        self.create()
        first = self.login()
        self.update(first, {"password": PASSWORD})
        second = self.login()
        self.assertTrue(first["authEpoch"] != second["authEpoch"], "reset did not rotate")
        self.assert_stale(first)
        self.assertTrue(self.store.native_authorize(self.authorization(second))["allowed"])
        self.store.change_own_password(second["username"], {"currentPassword": PASSWORD, "newPassword": PASSWORD})
        third = self.login()
        self.assertTrue(second["authEpoch"] != third["authEpoch"], "self-change did not rotate")
        self.assert_stale(second)
        self.assertTrue(self.store.native_authorize(self.authorization(third))["allowed"])

    def test_enabled_changes_rotate_but_noop_roles_scopes_and_profile_do_not(self):
        self.create(scopes=[{"kind": "camera", "id": "camera-a"}])
        identity = self.login()
        for patch in ({"enabled": True}, {"roles": ["operator"]},
                      {"scopes": [{"kind": "camera", "id": "camera-b"}]}):
            self.update(identity, patch)
            self.assertTrue(self.login()["authEpoch"] == identity["authEpoch"], "non-identity update rotated")
        self.store.update_account_profile(identity["username"], {"displayName": "Synthetic name", "avatar": "eye"})
        self.assertTrue(self.login()["authEpoch"] == identity["authEpoch"], "profile update rotated")
        self.assert_api_error(403, lambda: self.store.native_authorize(self.authorization(identity, camera="camera-a")),
                              "permission_rejected", "permission or resource scope was rejected")
        self.assertTrue(self.store.native_authorize(self.authorization(identity, "ptz.control", "camera-b"))["allowed"])
        self.update(identity, {"enabled": False})
        self.assert_stale(identity)
        disabled_epoch = self.store.db.execute("SELECT auth_epoch FROM users WHERE id=?", (identity["userId"],)).fetchone()[0]
        self.assertTrue(disabled_epoch != identity["authEpoch"], "disable did not rotate")
        self.update(identity, {"enabled": False})
        self.assertTrue(self.store.db.execute("SELECT auth_epoch FROM users WHERE id=?", (identity["userId"],)).fetchone()[0]
                        == disabled_epoch, "disabled noop rotated")
        self.update(identity, {"enabled": True})
        revived = self.login()
        self.assertTrue(revived["authEpoch"] != disabled_epoch, "enable did not rotate")
        self.assert_stale(identity)

    def test_recreated_username_never_rebinds_old_identity(self):
        self.create()
        old = self.login()
        with self.store.lock, self.store.db:
            # There is deliberately no product delete API.
            self.store.db.execute("DELETE FROM users WHERE id=?", (old["userId"],))
        self.create()
        current = self.login()
        self.assertTrue(current["userId"] != old["userId"], "fixture identity was reused")
        self.assert_stale(old)
        self.assertTrue(self.store.native_authorize(self.authorization(current))["allowed"])

    def test_missing_disabled_and_identity_mismatch_share_uniform_404(self):
        self.create()
        identity = self.login()
        for patch in ({"username": "unknown-one"}, {"userId": "f" * 32}, {"authEpoch": "e" * 32}):
            request = {**self.authorization(identity), **patch}
            self.assert_api_error(404, lambda: self.store.native_authorize(request),
                                  "user_not_found", "user is not managed by RBAC")
        self.update(identity, {"enabled": False})
        self.assert_stale(identity)

    def test_native_exact_fields_types_and_strict_lowercase_guards(self):
        self.create()
        identity = self.login()
        valid = self.authorization(identity)
        requests = [{key: val for key, val in valid.items() if key != missing} for missing in valid]
        requests += [{**valid, "groupId": "group-a"}, {**valid, "unexpected": True}]
        for field in ("userId", "authEpoch"):
            for bad in (None, 1, True, [], "", "f" * 31, "f" * 33, "A" * 32, "g" * 32, "f" * 32 + "\n"):
                requests.append({**valid, field: bad})
        requests += [{**valid, "username": None}, {**valid, "permission": []},
                     {**valid, "permission": "unknown"}, {**valid, "cameraId": None}, {**valid, "cameraId": "../bad"}]
        for request in requests:
            self.assert_api_error(400, lambda: self.store.native_authorize(request))
        login = {"username": "viewer-one", "password": PASSWORD, "clientKey": "fixture"}
        invalid_logins = [{key: val for key, val in login.items() if key != missing} for missing in login]
        invalid_logins += [{**login, "authEpoch": "f" * 32}, {**login, "username": 1}, {**login, "password": None},
                           {**login, "clientKey": ""}, {**login, "clientKey": []}, {**login, "password": "x" * 129},
                           {**login, "password": "\ud800"}]
        for request in invalid_logins:
            self.assert_api_error(400, lambda: self.store.native_login(request))

    def test_registry_group_is_resolved_internally_and_permission_denies_are_403(self):
        self.create(scopes=[{"kind": "group", "id": "group-a"}])
        identity = self.login()
        self.assertTrue(self.store.native_authorize(self.authorization(identity, camera="camera-a"))["allowed"])
        for permission, camera in (("live.view", "camera-b"), ("settings.manage", "")):
            self.assert_api_error(403, lambda: self.store.native_authorize(self.authorization(identity, permission, camera)),
                                  "permission_rejected", "permission or resource scope was rejected")
        with contextlib.closing(sqlite3.connect(self.registry)) as db, db:
            db.execute("UPDATE cameras SET group_id='group-b' WHERE id='camera-a'")
        self.assert_api_error(403, lambda: self.store.native_authorize(self.authorization(identity, camera="camera-a")))

    def test_real_sqlite_transaction_precedes_verifier_and_binding_permission_reads(self):
        self.create()
        original_verify = self.store.hasher.verify
        original_principal = self.store.principal
        observed = []
        with contextlib.closing(sqlite3.connect(self.store.path, timeout=0)) as writer:
            def assert_reserved():
                self.assertTrue(self.store.db.in_transaction, "native read was outside a SQLite transaction")
                try:
                    writer.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as error:
                    self.assertIn("locked", str(error))
                    observed.append(True)
                else:
                    writer.rollback()
                    self.fail("external writer entered a native identity snapshot")

            def verify(encoded, password):
                assert_reserved()
                return original_verify(encoded, password)

            with mock.patch.object(self.store.hasher, "verify", side_effect=verify):
                identity = self.login()

            def principal(user_id):
                assert_reserved()
                return original_principal(user_id)

            with mock.patch.object(self.store, "principal", side_effect=principal):
                self.store.native_authorize(self.authorization(identity))
        self.assertEqual(len(observed), 2)
        self.assertFalse(self.store.db.in_transaction)

    def test_native_handler_internal_token_gates_body_parsing_and_exact_success_bodies(self):
        self.create()
        login = {"username": "viewer-one", "password": PASSWORD, "clientKey": "fixture"}
        identity = self.login()
        for path, value in (("/auth/native-login", login), ("/auth/native-authorize", self.authorization(identity))):
            for token in (None, "synthetic-wrong-token"):
                status, result = self.request(path, value, token=token, raw=b"not json")
                self.assertEqual(status, 403)
                self.assertEqual(result["error"]["code"], "internal_auth_rejected")
            status, _ = self.request(path, value, raw=b"not json")
            self.assertEqual(status, 400)
        status, result = self.request("/auth/native-login", login)
        self.assertEqual(status, 200)
        self.assertTrue(result == identity, "native login body mismatch")
        status, result = self.request("/auth/native-authorize", self.authorization(identity))
        self.assertEqual(status, 200)
        self.assertEqual(set(result), {"allowed", "userId", "authEpoch", "permission"})
        self.assertTrue(result["authEpoch"] == identity["authEpoch"], "native grant changed guard")
        status, result = self.request("/auth/native-login", {**login, "password": "synthetic-wrong-password"})
        self.assertEqual(status, 401)
        self.assertEqual(result["error"]["code"], "invalid_credentials")

    def test_legacy_login_and_authorization_keep_success_protocol_and_token_behavior(self):
        self.create()
        status, login = self.request("/auth/login", {"username": "viewer-one", "password": PASSWORD,
            "clientKey": "legacy-fixture"}, token=None)
        self.assertEqual(status, 200)
        self.assertEqual(set(login), {"userId", "username", "roles", "permissions", "scopes"})
        status, result = self.request("/auth/authorize", {"username": "viewer-one", "permission": "live.view"})
        self.assertEqual(status, 200)
        self.assertTrue(result == {"allowed": True, "userId": login["userId"], "permission": "live.view"},
                        "legacy grant body changed")
        status, _ = self.request("/auth/authorize", {"username": "viewer-one", "permission": "live.view"}, token=None)
        self.assertEqual(status, 403)
        for _ in range(5):
            status, _ = self.request("/auth/login", {"username": "viewer-one", "password": "synthetic-wrong-password",
                "clientKey": "limited-fixture"}, token=None)
            self.assertEqual(status, 401)
        status, _ = self.request("/auth/login", {"username": "viewer-one", "password": PASSWORD,
            "clientKey": "limited-fixture"}, token=None)
        self.assertEqual(status, 429)
        self.assertEqual(self.store.db.execute("SELECT result FROM rbac_audit ORDER BY id DESC LIMIT 1").fetchone()[0],
                         "rate-limited")

    def test_native_database_and_verifier_faults_are_503_without_detail(self):
        self.create()
        identity = self.login()
        with mock.patch.object(self.store.hasher, "verify", side_effect=RuntimeError("synthetic verifier failure")):
            status, result = self.request("/auth/native-login", {"username": "viewer-one", "password": PASSWORD,
                "clientKey": "fixture"})
            self.assertEqual(status, 503)
            self.assertEqual(result["error"]["code"], "native_auth_unavailable")
            self.assertNotIn("synthetic verifier failure", json.dumps(result))
        self.store.close()
        status, result = self.request("/auth/native-authorize", self.authorization(identity))
        self.assertEqual(status, 503)
        self.assertEqual(result["error"]["code"], "native_auth_unavailable")


if __name__ == "__main__":
    unittest.main()
