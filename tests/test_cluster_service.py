#!/usr/bin/env python3
"""Deterministic v2-M7 RBAC, node, volume and lease contract tests."""

from __future__ import annotations

import hashlib
import base64
import datetime as dt
import http.server
import importlib.machinery
import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile
import threading
import time
from unittest import mock
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = pathlib.Path(__import__("os").environ.get(
    "WEBOBS_TEST_CLUSTER_SERVICE", ROOT / "cluster" / "cluster_service.py"))
LOADER = importlib.machinery.SourceFileLoader("webobs_cluster_service", str(SERVICE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC and SPEC.loader
cluster = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cluster
SPEC.loader.exec_module(cluster)


class FakeHasher:
    def hash(self, password: str) -> str:
        if len(password.encode()) < 16:
            raise cluster.ApiError(400, "invalid_password", "password too short")
        return "fixture$" + hashlib.sha256(password.encode()).hexdigest()

    def verify(self, encoded: str, password: str) -> bool:
        return encoded == self.hash(password)


class FakeSigner:
    def __init__(self) -> None:
        self.counter = 0

    def sign(self, node_id: str, csr: str) -> tuple[str, str, int]:
        if "BEGIN CERTIFICATE REQUEST" not in csr:
            raise cluster.ApiError(400, "invalid_csr", "bad CSR")
        self.counter += 1
        return f"CERTIFICATE:{node_id}:{self.counter}", f"{node_id[:12]}{self.counter:04d}", 4_000_000 + self.counter


def heartbeat(node_time: int, *, free: int = 800) -> dict:
    return {
        "version": "2.3.0",
        "nodeTime": node_time,
        "capabilities": {"vaapi": {"runtimeProbePassed": True}},
        "volumes": [{
            "id": "hot-1", "label": "Hot 1", "tier": "hot", "state": "online",
            "capacityBytes": max(1000, free + 100), "freeBytes": free, "reserveBytes": 50,
            "highWatermark": 0.9, "lowWatermark": 0.8, "readOnly": False,
        }],
        "resources": {
            "cpuCores": 8, "memoryBytes": 8 * 1024 * 1024 * 1024,
            "capabilities": {"encode": ["h264-vaapi"]},
            "reservations": [{"taskType": "record-copy", "count": 1}], "rated": True,
        },
    }


class ClusterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.secrets = self.root / "secrets"
        self.secrets.mkdir()
        self.camera_registry = self.root / "cameras.sqlite3"
        camera_database = sqlite3.connect(self.camera_registry)
        camera_database.execute("CREATE TABLE cameras(id TEXT PRIMARY KEY,group_id TEXT NOT NULL)")
        camera_database.executemany("INSERT INTO cameras VALUES(?,?)", [
            ("camera-grouped", "group-1"), ("camera-1", ""),
        ])
        camera_database.execute("CREATE TABLE stream_profiles(id TEXT NOT NULL,camera_id TEXT NOT NULL,PRIMARY KEY(camera_id,id))")
        camera_database.executemany("INSERT INTO stream_profiles VALUES(?,?)", [
            ("main", "camera-1"), ("profile-1", "camera-1"), ("sub", "camera-1"),
            ("main", "camera-grouped"),
        ])
        camera_database.execute("""CREATE TABLE analytics_policies(
            camera_id TEXT NOT NULL, profile_id TEXT NOT NULL,
            person_enabled INTEGER NOT NULL DEFAULT 0,
            person_execution_preference TEXT NOT NULL DEFAULT 'auto',
            person_allow_server_fallback INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(camera_id, profile_id))""")
        camera_database.execute(
            "INSERT INTO analytics_policies(camera_id,profile_id,person_enabled,person_execution_preference,"
            "person_allow_server_fallback) VALUES(?,?,?,?,?)",
            ("camera-1", "sub", 1, "worker", 0),
        )
        camera_database.commit()
        camera_database.close()
        self.store = cluster.ClusterStore(self.root / "cluster.sqlite3",
                                          FakeHasher(), FakeSigner(), self.secrets,
                                          self.camera_registry)

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def create_user(self, username: str = "operator-one", roles: list[str] | None = None) -> dict:
        return self.store.create_user({
            "username": username, "password": "correct-horse-battery",
            "roles": roles or ["operator"],
            "scopes": [{"kind": "camera", "id": "camera-1"}],
        })

    def enroll(self, name: str = "Recorder A", role: str = "recorder") -> tuple[str, str, str]:
        created = self.store.create_enrollment({"name": name, "role": role})
        csr = "-----BEGIN CERTIFICATE REQUEST-----\nfixture\n-----END CERTIFICATE REQUEST-----"
        submitted = self.store.submit_enrollment({"id": created["id"], "token": created["token"], "csr": csr})
        self.assertEqual(submitted["state"], "submitted")
        approved = self.store.approve_enrollment(created["id"])
        complete = self.store.complete_enrollment(created["id"], created["token"])
        self.assertEqual(complete["nodeId"], approved["nodeId"])
        return approved["nodeId"], created["id"], created["token"]

    def test_roles_are_deny_by_default_and_scoped(self) -> None:
        created = self.create_user()
        principal = self.store.authenticate("operator-one", "correct-horse-battery")
        self.assertIsNotNone(principal)
        assert principal
        self.assertTrue(principal.permits("ptz.control", "camera-1"))
        self.assertFalse(principal.permits("ptz.control", "camera-2"))
        self.assertFalse(principal.permits("recording.delete", "camera-1"))
        self.assertFalse(principal.permits("user.manage"))
        self.assertFalse(principal.permits("playback.view", "collection-scope"))
        self.assertIsNone(self.store.authenticate("operator-one", "wrong-password-value"))
        listed = self.store.list_users()["users"][0]
        self.assertEqual(listed["id"], created["id"])
        self.assertNotIn("password", str(listed).lower())

    def test_complete_builtin_role_matrix_and_group_scope(self) -> None:
        expected = {
            "admin": cluster.PERMISSIONS,
            "operator": frozenset({"live.view", "scene.read", "playback.view",
                                    "snapshot.create", "ptz.control", "talk.control",
                                    "event.ack", "recording.lock", "analytics.view", "analytics.run"}),
            "viewer": frozenset({"live.view", "scene.read", "playback.view", "analytics.view", "analytics.run"}),
            "auditor": frozenset({"event.ack", "audit.view", "playback.view", "analytics.view"}),
            "exporter": frozenset({"playback.view", "export.create"}),
        }
        self.assertEqual(cluster.ROLE_PERMISSIONS, expected)
        for role, permissions in expected.items():
            created = self.store.create_user({
                "username": f"matrix-{role}", "password": "correct-horse-battery",
                "roles": [role], "scopes": [{"kind": "group", "id": "group-1"}],
            })
            principal = self.store.principal(created["id"])
            self.assertEqual(principal.permissions, permissions)
            for permission in cluster.PERMISSIONS:
                self.assertEqual(permission in principal.permissions,
                                 permission in permissions, f"{role}: {permission}")
            if role != "admin" and "live.view" in permissions:
                self.assertTrue(principal.permits("live.view", "camera-other", "group-1"))
                self.assertFalse(principal.permits("live.view", "camera-other", "group-2"))
        self.assertTrue(self.store.authorize("matrix-viewer", "live.view", "camera-grouped")["allowed"])
        with self.assertRaisesRegex(cluster.ApiError, "scope"):
            self.store.authorize("matrix-viewer", "live.view", "camera-unknown")

    def test_user_validation_and_unique_name(self) -> None:
        self.assertFalse(self.store.has_enabled_admin())
        cluster.validate_compatibility_auth("true", self.store)
        with self.assertRaisesRegex(RuntimeError, "database administrator"):
            cluster.validate_compatibility_auth("false", self.store)
        with self.assertRaisesRegex(RuntimeError, "true or false"):
            cluster.validate_compatibility_auth("disabled", self.store)
        self.create_user()
        self.assertFalse(self.store.has_enabled_admin())
        with self.assertRaisesRegex(cluster.ApiError, "username already exists"):
            self.create_user()
        with self.assertRaises(cluster.ApiError):
            self.store.create_user({"username": "bad", "password": "short", "roles": ["admin"],
                                    "scopes": [{"kind": "all", "id": "camera-1"}]})
        self.assertEqual(cluster.ROLE_PERMISSIONS["exporter"],
                         frozenset({"playback.view", "export.create"}))
        self.create_user("database-admin", ["admin"])
        self.assertTrue(self.store.has_enabled_admin())
        cluster.validate_compatibility_auth("false", self.store)

    def test_rbac_audit_is_bounded_paginated_and_redacted(self) -> None:
        first = self.create_user(username="audit-user-one")
        second = self.create_user(username="audit-user-two")
        page = self.store.list_audit({"limit": ["1"]})
        self.assertEqual(len(page["records"]), 1)
        self.assertEqual(page["records"][0]["subjectId"], second["id"])
        self.assertIsInstance(page["nextBefore"], int)
        following = self.store.list_audit({"limit": ["2"], "before": [str(page["nextBefore"])]})
        self.assertEqual(following["records"][0]["subjectId"], first["id"])
        self.assertEqual(set(following["records"][0]),
                         {"id", "event", "actorId", "subjectId", "result", "createdAt"})
        with self.assertRaisesRegex(cluster.ApiError, "pagination"):
            self.store.list_audit({"limit": ["257"]})

    def test_user_patch_is_revisioned_and_last_admin_is_protected(self) -> None:
        admin = self.create_user("admin-one", ["admin"])
        with self.assertRaisesRegex(cluster.ApiError, "last enabled"):
            self.store.update_user(admin["id"], {"enabled": False}, admin["revision"])
        second = self.create_user("admin-two", ["admin"])
        updated = self.store.update_user(admin["id"], {
            "enabled": False, "roles": ["viewer"], "scopes": []}, admin["revision"])
        self.assertFalse(updated["enabled"])
        with self.assertRaisesRegex(cluster.ApiError, "revision"):
            self.store.update_user(second["id"], {"roles": ["viewer"]}, 99)

    def test_authentication_is_rate_limited_and_authorization_is_server_side(self) -> None:
        user = self.create_user()
        for attempt in range(5):
            self.assertIsNone(self.store.authenticate("operator-one", "wrong-password-value", "client-1",
                                                      timestamp=100 + attempt))
        with self.assertRaisesRegex(cluster.ApiError, "too many"):
            self.store.authenticate("operator-one", "wrong-password-value", "client-1", timestamp=106)
        allowed = self.store.authorize("operator-one", "live.view", "camera-1")
        self.assertTrue(allowed["allowed"])
        with self.assertRaisesRegex(cluster.ApiError, "scope"):
            self.store.authorize("operator-one", "live.view", "camera-2")
        with self.assertRaises(cluster.ApiError):
            self.store.authorize("operator-one", "recording.delete", "camera-1")
        self.assertIsNotNone(self.store.authenticate(
            "operator-one", "correct-horse-battery", "client-2", timestamp=200))
        records = self.store.list_audit({"limit": ["32"]})["records"]
        login_records = [record for record in records if record["event"] == "auth.login"]
        self.assertEqual({record["result"] for record in login_records},
                         {"rejected", "rate-limited", "succeeded"})
        self.assertTrue(any(record["actorId"] == user["id"] and record["result"] == "succeeded"
                            for record in login_records))
        self.assertTrue(all(record["actorId"] in {"anonymous", user["id"]}
                            and record["subjectId"] == "session" for record in login_records))
        authorization_records = [record for record in records
                                 if record["event"] == "auth.authorization"]
        self.assertEqual(len(authorization_records), 2)
        self.assertEqual({record["subjectId"] for record in authorization_records},
                         {"live.view", "recording.delete"})
        serialized = str(records).lower()
        self.assertNotIn("operator-one", serialized)
        self.assertNotIn("wrong-password", serialized)
        self.assertNotIn("client-1", serialized)

    def test_one_time_enrollment_and_redacted_node_listing(self) -> None:
        node_id, enrollment_id, token = self.enroll()
        with self.assertRaises(cluster.ApiError):
            self.store.complete_enrollment(enrollment_id, token)
        nodes = self.store.list_nodes(timestamp=100)["nodes"]
        self.assertEqual(nodes[0]["id"], node_id)
        self.assertNotIn("certificate:", str(nodes).lower())
        self.assertNotIn("serial", str(nodes).lower())
        self.assertNotIn(token, str(nodes))

    def test_certificate_renewal_rotates_serial_and_header_cannot_impersonate_node(self) -> None:
        node_id, _, _ = self.enroll()
        csr = "-----BEGIN CERTIFICATE REQUEST-----\nrenew\n-----END CERTIFICATE REQUEST-----"
        renewed = self.store.renew_certificate(node_id, {"csr": csr})
        self.assertEqual(renewed["nodeId"], node_id)
        self.assertIn(":2", renewed["certificate"])

        handler = cluster.ClusterHandler.__new__(cluster.ClusterHandler)
        handler.command = "POST"
        handler.path = "/internal/v1/nodes/heartbeat"
        handler.headers = {"X-WebObs-Node-Id": node_id}
        handler.connection = object()
        previous = cluster.STORE
        cluster.STORE = self.store
        try:
            with self.assertRaisesRegex(cluster.ApiError, "mTLS identity"):
                handler.handle_request()
        finally:
            cluster.STORE = previous

    def test_heartbeat_volume_resource_and_clock_skew(self) -> None:
        node_id, _, _ = self.enroll()
        result = self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        self.assertEqual(result["status"], "online")
        self.assertEqual(self.store.list_volumes()["volumes"][0]["id"], "hot-1")
        capacity = self.store.capacity()["nodes"][0]
        self.assertTrue(capacity["rated"])
        self.assertEqual(capacity["reservations"][0]["taskType"], "record-copy")
        skewed = heartbeat(1010)
        self.assertEqual(self.store.heartbeat(node_id, skewed, timestamp=1000)["status"], "clock-skew")
        with self.assertRaisesRegex(cluster.ApiError, "not eligible"):
            self.store.assign("camera-1", "profile-1", node_id, timestamp=1000)

    def test_volume_policy_archive_target_and_backup_job_are_bounded(self) -> None:
        node_id, _, _ = self.enroll()
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        volume = self.store.list_volumes()["volumes"][0]
        updated = self.store.update_volume(node_id, "hot-1", {
            "label": "Evidence hot", "highWatermark": 0.88, "lowWatermark": 0.77,
        }, volume["revision"])
        self.assertEqual(updated["label"], "Evidence hot")
        self.store.heartbeat(node_id, heartbeat(1001), timestamp=1001)
        preserved = self.store.list_volumes()["volumes"][0]
        self.assertEqual(preserved["label"], "Evidence hot")
        self.assertEqual(preserved["highWatermark"], 0.88)
        assignment_snapshot = self.store.assignments_for(node_id)
        self.assertEqual(assignment_snapshot["volumes"][0]["lowWatermark"], 0.77)
        with self.assertRaisesRegex(cluster.ApiError, "HTTPS authority"):
            self.store.create_archive_target({
                "name": "bad", "endpoint": "http://user:pass@example.test/path",
                "bucket": "webobs-archive", "credentialsRef": "s3-main",
            })
        target = self.store.create_archive_target({
            "name": "MinIO archive", "endpoint": "https://minio.example.test:9000",
            "bucket": "webobs-archive", "credentialsRef": "s3-main",
        })
        self.assertNotIn("password", str(target).lower())
        job = self.store.create_backup_job({"targetId": target["id"]})
        self.assertEqual(job["state"], "queued")
        claimed = self.store.claim_backup_job()["job"]
        self.assertEqual(claimed["id"], job["id"])
        completed = self.store.complete_backup_job(job["id"], {
            "state": "completed", "sha256": "c" * 64,
        })
        self.assertEqual(completed["state"], "completed")
        self.assertEqual(self.store.list_backup_jobs()["jobs"][0]["sha256"], "c" * 64)

    def test_external_provider_gets_only_bounded_ephemeral_media_grant(self) -> None:
        provider = self.store.create_provider({
            "name": "Detector fixture", "endpoint": "https://provider.example.test/webobs/provider/v1/tasks",
            "taskTypes": ["detector"], "credentialsRef": "provider-detector",
            "maxConcurrent": 1,
        })
        task = self.store.create_provider_task(provider["id"], {
            "taskType": "detector", "cameraId": "camera-1", "profileId": "sub",
            "parameters": {"model": "person"},
        })
        self.assertEqual(task["state"], "offered")
        self.assertLessEqual(task["expiresAt"] - cluster.now_seconds(), 60)
        self.assertEqual(task["mediaGrant"]["method"], "GET")
        serialized = str(task).lower()
        self.assertNotIn("credentials", serialized)
        self.assertNotIn("endpoint", serialized)
        with self.assertRaisesRegex(cluster.ApiError, "capacity"):
            self.store.create_provider_task(provider["id"], {
                "taskType": "detector", "cameraId": "camera-2", "profileId": "sub",
            })
        token = task["mediaGrant"]["token"]
        consumed = self.store.consume_provider_grant(task["taskId"], token)
        self.assertEqual(consumed["cameraId"], "camera-1")
        self.assertEqual(consumed["credentialExposure"], "none")
        listed = self.store.list_provider_tasks(provider["id"], {"limit": ["10"]})
        self.assertEqual(listed["tasks"][0]["state"], "media-opened")
        self.assertIsNotNone(listed["tasks"][0]["mediaOpenedAt"])
        self.assertNotIn("parameters", listed["tasks"][0])
        self.assertNotIn("token", str(listed).lower())
        provider_status = self.store.list_providers()["providers"][0]
        self.assertEqual(provider_status["taskCounts"], {"media-opened": 1})
        with self.assertRaisesRegex(cluster.ApiError, "rejected"):
            self.store.consume_provider_grant(task["taskId"], token)

        self.store._expire_provider_tasks(task["expiresAt"] + 1)
        expired = self.store.list_provider_tasks(provider["id"], {})["tasks"][0]
        self.assertEqual(expired["state"], "expired")
        self.assertEqual(expired["resultCode"], "grant_expired")
        replacement = self.store.create_provider_task(provider["id"], {
            "taskType": "detector", "cameraId": "camera-2", "profileId": "sub",
        })
        self.assertEqual(replacement["state"], "offered")

        with self.assertRaisesRegex(cluster.ApiError, "limit"):
            self.store.list_provider_tasks(provider["id"], {"limit": ["257"]})

    def test_provider_recording_grant_is_bound_to_catalog_camera_and_profile(self) -> None:
        node_id, _, _ = self.enroll("Provider recorder")
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        self.store.assign("camera-1", "main", node_id, timestamp=1000)
        segment_id = "a" * 32
        self.store.accept_catalog(node_id, {"segments": [{
            "segmentId": segment_id, "cameraId": "camera-1", "profileId": "main",
            "volumeId": "hot-1", "storageKey": "camera-1/segment.mp4", "sizeBytes": 1024,
            "sha256": "b" * 64, "generation": 1, "archiveState": "local", "integrity": "ok",
        }]})
        provider = self.store.create_provider({
            "name": "Exporter fixture", "endpoint": "https://provider.example.test/tasks",
            "taskTypes": ["export"], "credentialsRef": "provider-export", "maxConcurrent": 2,
        })
        with self.assertRaisesRegex(cluster.ApiError, "not found"):
            self.store.create_provider_task(provider["id"], {
                "taskType": "export", "cameraId": "camera-other", "profileId": "main",
                "segmentId": segment_id,
            })
        task = self.store.create_provider_task(provider["id"], {
            "taskType": "export", "cameraId": "camera-1", "profileId": "main",
            "segmentId": segment_id,
        })
        grant = self.store.consume_provider_grant(task["taskId"], task["mediaGrant"]["token"])
        self.assertEqual(grant["segmentId"], segment_id)

    def test_lease_renewal_isolation_and_generation_fencing(self) -> None:
        first, _, _ = self.enroll("Recorder A")
        second, _, _ = self.enroll("Recorder B")
        self.store.heartbeat(first, heartbeat(1000), timestamp=1000)
        self.store.heartbeat(second, heartbeat(1000), timestamp=1000)
        assignment = self.store.assign("camera-1", "profile-1", first, timestamp=1000)
        self.assertEqual(assignment["leaseExpiresAt"], 1030)
        self.assertEqual(assignment["isolationDeadline"], 1150)
        renewed = self.store.renew(first, {"cameraId": "camera-1", "profileId": "profile-1", "generation": 1},
                                   timestamp=1010)
        self.assertEqual(renewed["leaseExpiresAt"], 1040)
        self.store.heartbeat(second, heartbeat(1149), timestamp=1149)
        with self.assertRaisesRegex(cluster.ApiError, "isolation deadline"):
            self.store.assign("camera-1", "profile-1", second, timestamp=1149)
        self.store.heartbeat(second, heartbeat(1160), timestamp=1160)
        moved = self.store.assign("camera-1", "profile-1", second, timestamp=1160)
        self.assertEqual(moved["generation"], 2)
        with self.assertRaisesRegex(cluster.ApiError, "stale"):
            self.store.renew(first, {"cameraId": "camera-1", "profileId": "profile-1", "generation": 1},
                             timestamp=1161)

    def test_job_result_is_owned_generation_fenced_and_redacted(self) -> None:
        owner, _, _ = self.enroll("Job owner")
        other, _, _ = self.enroll("Other recorder")
        self.store.heartbeat(owner, heartbeat(1000), timestamp=1000)
        self.store.heartbeat(other, heartbeat(1000), timestamp=1000)
        costs = {"cpuCores": 0.25, "memoryBytes": 1024, "decodeSlots": 0,
                 "encodeSlots": 0, "diskBytesPerSecond": 0}
        self.store.assign("camera-job", "main", owner, task_type="export", costs=costs,
                          timestamp=1000)
        offered = self.store.assignments_for(owner)["assignments"][0]
        self.assertEqual(offered["taskType"], "export")
        self.assertEqual(offered["costs"], costs)
        with self.assertRaisesRegex(cluster.ApiError, "stale"):
            self.store.report_job_result(other, {
                "cameraId": "camera-job", "profileId": "main", "generation": 1,
                "state": "completed",
            }, timestamp=1001)
        with self.assertRaisesRegex(cluster.ApiError, "stale"):
            self.store.report_job_result(owner, {
                "cameraId": "camera-job", "profileId": "main", "generation": 2,
                "state": "completed",
            }, timestamp=1001)
        result = self.store.report_job_result(owner, {
            "cameraId": "camera-job", "profileId": "main", "generation": 1,
            "state": "failed", "resultCode": "fixture_failed",
        }, timestamp=1002)
        self.assertEqual(result["state"], "failed")
        placement = self.store.list_placements()["placements"][0]
        self.assertEqual(placement["state"], "failed")
        self.assertEqual(placement["leaseExpiresAt"], 0)
        self.assertEqual(placement["isolationDeadline"], 0)
        with self.assertRaisesRegex(cluster.ApiError, "stale"):
            self.store.renew(owner, {
                "cameraId": "camera-job", "profileId": "main", "generation": 1,
            }, timestamp=1003)
        with self.assertRaisesRegex(cluster.ApiError, "stale"):
            self.store.report_job_result(owner, {
                "cameraId": "camera-job", "profileId": "main", "generation": 1,
                "state": "failed", "resultCode": "retry",
            }, timestamp=1003)
        audit = self.store.list_audit({"limit": ["32"]})["records"]
        record = next(item for item in audit if item["event"] == "node.job.result")
        self.assertEqual(record["actorId"], owner)
        self.assertEqual(record["result"], "failed")
        self.assertNotIn("camera-job", str(record))
        self.assertNotIn("fixture_failed", str(audit))

    def test_job_result_rejects_unbounded_failure_details(self) -> None:
        node_id, _, _ = self.enroll("Invalid result recorder")
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        self.store.assign("camera-job", "main", node_id, timestamp=1000)
        with self.assertRaisesRegex(cluster.ApiError, "job result"):
            self.store.report_job_result(node_id, {
                "cameraId": "camera-job", "profileId": "main", "generation": 1,
                "state": "failed", "resultCode": "https://secret.example.test/failure",
            })
        with self.assertRaisesRegex(cluster.ApiError, "job result"):
            self.store.report_job_result(node_id, {
                "cameraId": "camera-job", "profileId": "main", "generation": 1,
                "state": "completed", "resultCode": "unexpected-detail",
            })

    def test_detector_job_is_worker_only_and_fenced_without_recording_assignment(self) -> None:
        worker, _, _ = self.enroll("Person detector", role="worker")
        self.store.heartbeat(worker, heartbeat(1000), timestamp=1000)
        job = self.store.create_analytics_job({
            "cameraId": "camera-1", "profileId": "sub", "kind": "person",
            "modelId": cluster.ANALYTICS_MODEL_ID, "modelSha256": cluster.ANALYTICS_MODEL_SHA256,
        }, timestamp=1000)
        self.assertEqual(job["nodeId"], worker)
        self.assertEqual(job["state"], "queued")
        self.assertEqual(self.store.assignments_for(worker)["assignments"], [])
        claimed = self.store.claim_analytics_job(worker, timestamp=1001)["job"]
        self.assertEqual(claimed["jobId"], job["jobId"])
        renewed = self.store.renew_analytics_job(worker, {
            "jobId": job["jobId"], "generation": job["generation"],
        }, timestamp=1010)
        self.assertEqual(renewed["generation"], job["generation"])
        result = self.store.report_analytics_job_result(worker, {
            "jobId": job["jobId"], "generation": job["generation"],
            "state": "completed", "resultCode": "", "modelSha256": cluster.ANALYTICS_MODEL_SHA256, "signals": [{
                "kind": "person", "confidence": .91,
                "boxes": [{"x": .1, "y": .2, "width": .3, "height": .4}],
                "occurredAt": 1_011_000,
            }],
        }, timestamp=1011)
        self.assertEqual(result["acceptedSignals"], 1)
        listed = self.store.list_analytics_jobs()["jobs"][0]
        self.assertEqual(listed["state"], "completed")
        self.assertEqual(self.store.capacity()["nodes"][0]["scheduledReservations"]["taskCount"], 0)
        with self.assertRaisesRegex(cluster.ApiError, "stale"):
            self.store.renew_analytics_job(worker, {"jobId": job["jobId"], "generation": 1}, timestamp=1012)

    def test_detector_job_rejects_model_digest_mismatch(self) -> None:
        worker, _, _ = self.enroll("Digest detector", role="worker")
        self.store.heartbeat(worker, heartbeat(1000), timestamp=1000)
        job = self.store.create_analytics_job({
            "cameraId": "camera-1", "profileId": "sub", "kind": "person",
            "modelId": cluster.ANALYTICS_MODEL_ID, "modelSha256": cluster.ANALYTICS_MODEL_SHA256,
        }, timestamp=1000)
        self.store.claim_analytics_job(worker, timestamp=1001)
        with self.assertRaisesRegex(cluster.ApiError, "digest"):
            self.store.report_analytics_job_result(worker, {
                "jobId": job["jobId"], "generation": job["generation"],
                "state": "completed", "resultCode": "", "modelSha256": "d" * 64,
                "signals": [{"kind": "person", "confidence": .8, "boxes": []}],
            }, timestamp=1001)

    def test_detector_job_rejects_non_worker_or_unapproved_model(self) -> None:
        recorder, _, _ = self.enroll("Recorder only", role="recorder")
        self.store.heartbeat(recorder, heartbeat(1000), timestamp=1000)
        with self.assertRaisesRegex(cluster.ApiError, "model"):
            self.store.create_analytics_job({
                "cameraId": "camera-1", "profileId": "sub", "kind": "person",
                "modelId": "../../unsafe", "modelSha256": cluster.ANALYTICS_MODEL_SHA256,
                "nodeId": recorder,
            }, timestamp=1000)
        with self.assertRaisesRegex(cluster.ApiError, "node"):
            self.store.create_analytics_job({
                "cameraId": "camera-1", "profileId": "sub", "kind": "person",
                "modelId": cluster.ANALYTICS_MODEL_ID, "modelSha256": cluster.ANALYTICS_MODEL_SHA256,
                "nodeId": recorder,
            }, timestamp=1000)

    def test_detector_job_requires_explicit_registry_worker_opt_in(self) -> None:
        worker, _, _ = self.enroll("Policy-gated detector", role="worker")
        self.store.heartbeat(worker, heartbeat(1000), timestamp=1000)
        database = sqlite3.connect(self.camera_registry)
        try:
            database.execute(
                "UPDATE analytics_policies SET person_enabled=0, person_execution_preference='auto', "
                "person_allow_server_fallback=0 WHERE camera_id=? AND profile_id=?",
                ("camera-1", "sub"),
            )
            database.commit()
        finally:
            database.close()
        with self.assertRaisesRegex(cluster.ApiError, "not authorized"):
            self.store.create_analytics_job({
                "cameraId": "camera-1", "profileId": "sub", "kind": "person",
                "modelId": cluster.ANALYTICS_MODEL_ID, "modelSha256": cluster.ANALYTICS_MODEL_SHA256,
            }, timestamp=1000)

        database = sqlite3.connect(self.camera_registry)
        try:
            database.execute(
                "UPDATE analytics_policies SET person_enabled=1, person_execution_preference='auto', "
                "person_allow_server_fallback=1 WHERE camera_id=? AND profile_id=?",
                ("camera-1", "sub"),
            )
            database.commit()
        finally:
            database.close()
        job = self.store.create_analytics_job({
            "cameraId": "camera-1", "profileId": "sub", "kind": "person",
            "modelId": cluster.ANALYTICS_MODEL_ID, "modelSha256": cluster.ANALYTICS_MODEL_SHA256,
        }, timestamp=1001)
        self.assertEqual(job["state"], "queued")

    def test_detector_claim_mints_bounded_media_grant_and_reads_loopback_frame(self) -> None:
        worker, _, _ = self.enroll("Frame worker", role="worker")
        current = int(time.time())
        self.store.heartbeat(worker, heartbeat(current), timestamp=current)
        job = self.store.create_analytics_job({
            "cameraId": "camera-1", "profileId": "sub", "kind": "person",
            "modelId": cluster.ANALYTICS_MODEL_ID, "modelSha256": cluster.ANALYTICS_MODEL_SHA256,
        }, timestamp=current)
        frame = {"width": 2, "height": 2,
                 "rgbaBase64": base64.b64encode(bytes(range(16))).decode("ascii"),
                 "capturedAt": current * 1000}

        class FrameHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                body = json.dumps(frame, separators=(",", ":")).encode("ascii")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FrameHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.dict(__import__("os").environ, {
                "WEBOBS_ANALYTICS_MEDIA_ENDPOINT": f"http://127.0.0.1:{server.server_port}/frame",
            }, clear=False):
                claimed = self.store.claim_analytics_job(worker, timestamp=current + 1)["job"]
                grant = claimed["mediaGrant"]
                self.assertEqual(grant["maxRequests"], 60)
                packet = self.store.consume_analytics_media_frame(worker, job["jobId"], grant["token"])
                self.assertEqual(packet["width"], 2)
                self.assertEqual(packet["remainingRequests"], 59)
                with self.assertRaisesRegex(cluster.ApiError, "rejected"):
                    self.store.consume_analytics_media_frame("0" * 32, job["jobId"], grant["token"])
                self.store.report_analytics_job_result(worker, {
                    "jobId": job["jobId"], "generation": job["generation"], "state": "completed",
                    "resultCode": "", "modelSha256": cluster.ANALYTICS_MODEL_SHA256, "signals": [],
                }, timestamp=current + 2)
                with self.assertRaisesRegex(cluster.ApiError, "rejected"):
                    self.store.consume_analytics_media_frame(worker, job["jobId"], grant["token"])
        finally:
            server.shutdown()
            server.server_close()
    def test_scheduler_is_stable_capacity_aware_and_never_silently_uses_cpu(self) -> None:
        first, _, _ = self.enroll("Recorder A")
        second, _, _ = self.enroll("Recorder B")
        self.store.heartbeat(first, heartbeat(1000, free=1 << 30), timestamp=1000)
        self.store.heartbeat(second, heartbeat(1000, free=3 << 30), timestamp=1000)
        selected = self.store.assign("camera-auto", "profile-1", timestamp=1000)
        self.assertEqual(selected["nodeId"], second)
        self.assertEqual(selected["taskType"], "record-copy")
        with self.assertRaisesRegex(cluster.ApiError, "CPU fallback was not started"):
            self.store.assign("camera-transcode", "profile-1", task_type="record-transcode",
                              costs={"encodeSlots": 1}, timestamp=1000)
        capacity = self.store.capacity()
        self.assertEqual(capacity["referenceTiers"]["copy-32"]["streams"], 32)

    def test_scheduler_reserves_declared_assignment_costs_and_checks_explicit_nodes(self) -> None:
        node, _, _ = self.enroll("Capacity recorder")
        report = heartbeat(1000, free=3 << 30)
        report["resources"]["reservations"] = []
        report["resources"]["memoryBytes"] = 64 * 1024 * 1024
        self.store.heartbeat(node, report, timestamp=1000)
        costs = {"memoryBytes": 40 * 1024 * 1024}
        self.store.assign("camera-first", "main", node, costs=costs, timestamp=1000)
        with self.assertRaisesRegex(cluster.ApiError, "CPU fallback was not started"):
            self.store.assign("camera-second", "main", node, costs=costs, timestamp=1001)
        row = self.store.db.execute(
            "SELECT task_type,costs_json FROM recording_assignments WHERE camera_id='camera-first'"
        ).fetchone()
        self.assertEqual(row["task_type"], "record-copy")
        self.assertEqual(json.loads(row["costs_json"])["memoryBytes"], 40 * 1024 * 1024)

    def test_catalog_marks_stale_generation_as_conflict(self) -> None:
        node_id, _, _ = self.enroll()
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        self.store.assign("camera-1", "profile-1", node_id, timestamp=1000)
        segment = {
            "segmentId": "segment-1", "cameraId": "camera-1", "profileId": "profile-1",
            "volumeId": "hot-1", "storageKey": "camera-1/2026/01/01/segment.mp4",
            "sizeBytes": 1024, "sha256": "a" * 64, "generation": 1,
            "archiveState": "local", "integrity": "ok",
        }
        self.assertEqual(self.store.accept_catalog(node_id, {"segments": [segment]})["conflicts"], 0)
        segment["generation"] = 0
        segment["segmentId"] = "segment-stale"
        self.assertEqual(self.store.accept_catalog(node_id, {"segments": [segment]})["conflicts"], 1)

    def test_cross_node_recording_timeline_preserves_location_and_archive_state(self) -> None:
        node_id, _, _ = self.enroll("Timeline recorder")
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        self.store.assign("camera-1", "main", node_id, timestamp=1000)
        self.store.accept_catalog(node_id, {"segments": [{
            "segmentId": "a" * 32, "cameraId": "camera-1", "profileId": "main",
            "volumeId": "hot-1", "storageKey": "camera-1/segment.mkv", "sizeBytes": 4096,
            "sha256": "b" * 64, "generation": 1, "archiveState": "uploaded", "integrity": "ok",
            "startUtcMs": 1_000_000, "endUtcMs": 1_010_000, "durationMs": 10_000,
            "kind": "continuous", "videoCodec": "h264", "audioCodec": "aac", "locked": True,
        }]})
        timeline = self.store.recording_timeline({
            "from": ["999000"], "to": ["1011000"], "cameraId": ["camera-1"],
        })
        segment = timeline["cameras"][0]["segments"][0]
        self.assertEqual(segment["nodeId"], node_id)
        self.assertEqual(segment["volumeId"], "hot-1")
        self.assertEqual(segment["archiveState"], "uploaded")
        self.assertEqual(segment["playbackState"], "archived")
        self.assertTrue(segment["locked"])
        self.assertNotIn("storageKey", str(timeline))

    def test_archived_playback_ticket_is_short_lived_camera_bound_and_presigned(self) -> None:
        (self.secrets / "archive-fixture.json").write_text(json.dumps({
            "accessKeyId": "fixture-access", "secretAccessKey": "fixture-secret-value",
        }), encoding="utf-8")
        self.store.create_archive_target({
            "name": "Archive fixture", "endpoint": "https://archive.example.test:9000",
            "bucket": "webobs-archive", "region": "us-east-1",
            "credentialsRef": "archive-fixture.json",
        })
        node_id, _, _ = self.enroll("Archive playback recorder")
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        self.store.assign("camera-1", "main", node_id, timestamp=1000)
        segment_id = "e" * 32
        self.store.accept_catalog(node_id, {"segments": [{
            "segmentId": segment_id, "cameraId": "camera-1", "profileId": "main",
            "volumeId": "hot-1", "storageKey": "camera-1/segment.mp4", "sizeBytes": 4096,
            "sha256": "f" * 64, "generation": 1, "archiveState": "uploaded", "integrity": "ok",
            "startUtcMs": 1_000_000, "endUtcMs": 1_010_000, "durationMs": 10_000,
            "kind": "continuous", "videoCodec": "h264", "audioCodec": "aac", "locked": False,
        }]})
        timestamp = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)
        ticket = self.store.archive_playback_ticket(segment_id, "camera-1", timestamp)
        self.assertEqual(ticket["expiresAt"], int(timestamp.timestamp()) + 60)
        self.assertEqual(ticket["credentialExposure"], "ephemeral")
        self.assertIn("X-Amz-Signature=", ticket["url"])
        self.assertIn("X-Amz-Expires=60", ticket["url"])
        self.assertNotIn("fixture-secret-value", str(ticket))
        self.assertEqual(ticket["contentType"], "video/mp4")
        with self.assertRaisesRegex(cluster.ApiError, "not found"):
            self.store.archive_playback_ticket(segment_id, "camera-2", timestamp)

    def test_catalog_rejects_inconsistent_timeline_metadata(self) -> None:
        node_id, _, _ = self.enroll("Invalid timeline recorder")
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        self.store.assign("camera-1", "main", node_id, timestamp=1000)
        with self.assertRaisesRegex(cluster.ApiError, "timeline metadata"):
            self.store.accept_catalog(node_id, {"segments": [{
                "segmentId": "c" * 32, "cameraId": "camera-1", "profileId": "main",
                "volumeId": "hot-1", "storageKey": "camera-1/segment.mkv", "sizeBytes": 4096,
                "sha256": "d" * 64, "generation": 1, "archiveState": "local", "integrity": "ok",
                "startUtcMs": 1000, "endUtcMs": 2000, "durationMs": 999,
                "kind": "continuous", "videoCodec": "h264", "audioCodec": "", "locked": False,
            }]})
        with self.assertRaisesRegex(cluster.ApiError, "camera filter"):
            self.store.recording_catalog({"cameraId": ["camera-1", "camera-2"]})

    def test_node_becomes_offline_after_twenty_seconds(self) -> None:
        node_id, _, _ = self.enroll()
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        nodes = self.store.list_nodes(timestamp=1021)["nodes"]
        self.assertEqual(nodes[0]["id"], node_id)
        self.assertEqual(nodes[0]["status"], "offline")

    def test_node_revocation_fences_assignments(self) -> None:
        node_id, _, _ = self.enroll()
        self.store.heartbeat(node_id, heartbeat(1000), timestamp=1000)
        self.store.assign("camera-1", "profile-1", node_id, timestamp=1000)
        node = self.store.list_nodes(timestamp=1000)["nodes"][0]
        revoked = self.store.revoke_node(node_id, node["revision"])
        self.assertEqual(revoked["state"], "revoked")
        self.assertEqual(self.store.list_placements()["placements"][0]["state"], "revoked")
        with self.assertRaisesRegex(cluster.ApiError, "not eligible"):
            self.store.assign("camera-2", "profile-1", node_id, timestamp=1001)


if __name__ == "__main__":
    unittest.main()
