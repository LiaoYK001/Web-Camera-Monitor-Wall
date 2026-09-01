#!/usr/bin/env python3
"""Deterministic v2-M7 RBAC, node, volume and lease contract tests."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
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
        self.store = cluster.ClusterStore(pathlib.Path(self.directory.name) / "cluster.sqlite3",
                                          FakeHasher(), FakeSigner())

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def create_user(self, username: str = "operator-one", roles: list[str] | None = None) -> dict:
        return self.store.create_user({
            "username": username, "password": "correct-horse-battery",
            "roles": roles or ["operator"],
            "scopes": [{"kind": "camera", "id": "camera-1"}],
        })

    def enroll(self, name: str = "Recorder A") -> tuple[str, str, str]:
        created = self.store.create_enrollment({"name": name, "role": "recorder"})
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
                                    "event.ack", "recording.lock"}),
            "viewer": frozenset({"live.view", "scene.read", "playback.view"}),
            "auditor": frozenset({"event.ack", "audit.view", "playback.view"}),
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

    def test_user_validation_and_unique_name(self) -> None:
        self.create_user()
        with self.assertRaisesRegex(cluster.ApiError, "username already exists"):
            self.create_user()
        with self.assertRaises(cluster.ApiError):
            self.store.create_user({"username": "bad", "password": "short", "roles": ["admin"],
                                    "scopes": [{"kind": "all", "id": "camera-1"}]})
        self.assertEqual(cluster.ROLE_PERMISSIONS["exporter"],
                         frozenset({"playback.view", "export.create"}))

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
        self.create_user()
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
        with self.assertRaisesRegex(cluster.ApiError, "rejected"):
            self.store.consume_provider_grant(task["taskId"], token)

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
