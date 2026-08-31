#!/usr/bin/env python3
"""v2-M7 NVR catalog, volume placement and recorder lease tests."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = pathlib.Path(__import__("os").environ.get(
    "WEBOBS_TEST_NVR_SERVICE", ROOT / "nvr" / "nvr_service.py"))
LOADER = importlib.machinery.SourceFileLoader("webobs_nvr_storage", str(SERVICE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC and SPEC.loader
nvr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = nvr
SPEC.loader.exec_module(nvr)


class NvrStorageTests(unittest.TestCase):
    @staticmethod
    def service(root: pathlib.Path) -> object:
        config = root / "nvr.json"
        config.write_text('{"schemaVersion":1,"cameras":[]}', encoding="utf-8")
        return nvr.NvrService(config, root / "storage")

    def test_catalog_v1_is_migrated_without_moving_recordings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "catalog.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript("""
              CREATE TABLE cameras(id TEXT PRIMARY KEY,name TEXT,policy TEXT,stream TEXT,mode TEXT,updated_utc_ms INTEGER);
              CREATE TABLE segments(id TEXT PRIMARY KEY,camera_id TEXT,start_utc_ms INTEGER,end_utc_ms INTEGER,
                duration_ms INTEGER,storage_key TEXT UNIQUE,kind TEXT,video_codec TEXT,audio_codec TEXT,
                size_bytes INTEGER,integrity TEXT,locked INTEGER DEFAULT 0,created_utc_ms INTEGER);
              CREATE TABLE exports(id TEXT PRIMARY KEY,audit_id TEXT,created_utc_ms INTEGER,storage_key TEXT,manifest_key TEXT,mode TEXT);
            """)
            connection.commit()
            connection.close()
            catalog = nvr.Catalog(path)
            columns = {row[1] for row in catalog.connection.execute("PRAGMA table_info(segments)")}
            self.assertTrue({"node_id", "profile_id", "volume_id", "sha256", "assignment_generation", "archive_state"} <= columns)
            self.assertEqual(catalog.connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertTrue(path.with_name(path.name + ".pre-v2.3.backup").is_file())
            catalog.connection.close()

    def test_volume_manager_uses_only_pre_mounted_safe_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            legacy = root / "legacy"
            mounted = root / "volumes"
            legacy.mkdir()
            mounted.mkdir()
            (mounted / "hot-a").mkdir()
            (mounted / "Bad Name").mkdir()
            manager = nvr.VolumeManager(legacy, mounted)
            self.assertEqual(set(manager.roots), {"default", "hot-a"})
            volume_id, selected = manager.choose(0, {"hot-a": {"highWatermark": 1.0}})
            self.assertEqual((volume_id, selected), ("hot-a", mounted / "hot-a"))
            with self.assertRaises(RuntimeError):
                manager.path("hot-a", "../escape.mp4")
            with self.assertRaisesRegex(RuntimeError, "no writable"):
                manager.choose(0, {"hot-a": {"state": "evacuating", "highWatermark": 0.9}})

    def test_recorder_requires_current_assignment_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            service = nvr.NvrService.__new__(nvr.NvrService)
            service.node_role = "recorder"
            service.node_id = "node-a"
            service.assignment_path = root / "assignments.json"
            camera = {"id": "local-camera", "cameraId": "camera-1", "stream": "main",
                      "mainProfileId": "main", "subProfileId": ""}
            self.assertIsNone(service.assignment_generation(camera))
            service.assignment_path.write_text(json.dumps({
                "nodeId": "node-a", "assignments": [{
                    "cameraId": "camera-1", "profileId": "main", "state": "active",
                    "generation": 7, "isolationDeadline": int(time.time()) + 60,
                }],
            }), encoding="utf-8")
            self.assertEqual(service.assignment_generation(camera), 7)

    def test_pressure_migration_verifies_digest_before_catalog_switch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            volumes = root / "volumes"
            (volumes / "hot-a").mkdir(parents=True)
            (volumes / "hot-b").mkdir()
            with mock.patch.dict(__import__("os").environ, {"WEBOBS_NVR_VOLUMES_ROOT": str(volumes)}):
                service = self.service(root)
            service.catalog.execute("INSERT INTO cameras VALUES(?,?,?,?,?,?)",
                                    ("camera-1", "Fixture", "off", "main", "copy", 1))
            payload = b"evidence-segment"
            storage_key = "camera/segment.mp4"
            source = service.volumes.path("hot-a", storage_key)
            source.parent.mkdir(parents=True)
            source.write_bytes(payload)
            digest = __import__("hashlib").sha256(payload).hexdigest()
            service.config["minFreeBytes"] = 0
            service.catalog.add_segment({
                "id": "a" * 32, "cameraId": "camera-1", "profileId": "main",
                "startUtcMs": 1, "endUtcMs": 2, "durationMs": 1, "storageKey": storage_key,
                "kind": "continuous", "videoCodec": "h264", "audioCodec": "",
                "sizeBytes": len(payload), "integrity": "ok", "nodeId": "standalone",
                "volumeId": "hot-a", "sha256": digest, "assignmentGeneration": 0,
                "archiveState": "local",
            })
            usage = lambda path: __import__("shutil")._ntuple_diskusage(100, 95 if pathlib.Path(path).name == "hot-a" else 10,
                                                                         5 if pathlib.Path(path).name == "hot-a" else 90)
            with mock.patch.object(nvr.shutil, "disk_usage", side_effect=usage):
                self.assertTrue(service.migrate_under_pressure())
            row = service.segment_row("a" * 32)
            self.assertEqual(row["volume_id"], "hot-b")
            self.assertFalse(source.exists())
            self.assertEqual(service.volumes.path("hot-b", storage_key).read_bytes(), payload)
            service.catalog.connection.close()

    def test_archived_playback_is_restored_and_reverified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            service = self.service(root)
            service.catalog.execute("INSERT INTO cameras VALUES(?,?,?,?,?,?)",
                                    ("camera-1", "Fixture", "off", "main", "copy", 1))
            payload = b"archived-segment"
            digest = __import__("hashlib").sha256(payload).hexdigest()
            service.catalog.add_segment({
                "id": "b" * 32, "cameraId": "camera-1", "profileId": "main",
                "startUtcMs": 1, "endUtcMs": 2, "durationMs": 1, "storageKey": "missing.mp4",
                "kind": "continuous", "videoCodec": "h264", "audioCodec": "",
                "sizeBytes": len(payload), "integrity": "ok", "nodeId": "standalone",
                "volumeId": "default", "sha256": digest, "assignmentGeneration": 0,
                "archiveState": "uploaded",
            })
            service.archive_retrieval_enabled = True

            def restore(command, **_kwargs):
                destination = pathlib.Path(command[command.index("--destination") + 1])
                destination.write_bytes(payload)
                return mock.Mock(returncode=0)

            with mock.patch.object(nvr.subprocess, "run", side_effect=restore):
                restored = service.media_path("b" * 32)
            self.assertEqual(restored.read_bytes(), payload)
            service.catalog.connection.close()


if __name__ == "__main__":
    unittest.main()
