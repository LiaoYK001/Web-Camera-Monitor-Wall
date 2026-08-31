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
            self.assertTrue({"node_id", "volume_id", "sha256", "assignment_generation", "archive_state"} <= columns)
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
            volume_id, selected = manager.choose(0)
            self.assertEqual((volume_id, selected), ("hot-a", mounted / "hot-a"))
            with self.assertRaises(RuntimeError):
                manager.path("hot-a", "../escape.mp4")

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


if __name__ == "__main__":
    unittest.main()
