#!/usr/bin/env python3
"""Deterministic node-agent filesystem and transport boundary tests."""

from __future__ import annotations

import importlib.util
import importlib.machinery
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = pathlib.Path(__import__("os").environ.get(
    "WEBOBS_TEST_NODE_AGENT", ROOT / "cluster" / "node_agent.py"))
LOADER = importlib.machinery.SourceFileLoader("webobs_node_agent", str(SERVICE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC and SPEC.loader
agent = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = agent
SPEC.loader.exec_module(agent)


class AgentTests(unittest.TestCase):
    def test_controller_requires_clean_https_authority(self) -> None:
        with tempfile.NamedTemporaryFile() as ca:
            for value in ("http://controller.test:9443", "https://user:pass@controller.test",
                          "https://controller.test/path", "https://controller.test/?token=x"):
                with self.assertRaises(agent.AgentError):
                    agent.ControllerClient(value, pathlib.Path(ca.name))

    def test_atomic_json_is_private_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "state" / "assignments.json"
            agent.atomic_json(target, {"assignments": [], "controllerOnline": False})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["assignments"], [])
            if os.name != "nt":
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_only_mounted_safe_volume_ids_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "hot-1").mkdir()
            (root / "Bad Volume").mkdir()
            (root / "not-a-volume.txt").write_text("x", encoding="ascii")
            values = agent.volume_inventory(root)
            self.assertEqual([item["id"] for item in values], ["hot-1"])
            self.assertGreater(values[0]["capacityBytes"], 0)

    def test_resource_report_does_not_claim_hardware_from_device_presence(self) -> None:
        report = agent.resource_report()
        self.assertIn("runtimeProbePassed", report["capabilities"])
        self.assertFalse(report["rated"])
        self.assertEqual(report["reservations"], [])

    def test_catalog_batch_only_exports_current_assignment_and_no_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = pathlib.Path(directory) / "catalog.sqlite3"
            connection = sqlite3.connect(catalog)
            connection.executescript("""
              CREATE TABLE segments(
                id TEXT,camera_id TEXT,profile_id TEXT,volume_id TEXT,storage_key TEXT,
                size_bytes INTEGER,sha256 TEXT,assignment_generation INTEGER,
                archive_state TEXT,integrity TEXT,created_utc_ms INTEGER);
            """)
            connection.execute("INSERT INTO segments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                "segment-1", "camera-1", "main", "hot-1", "camera-1/a.mp4", 10,
                "a" * 64, 3, "local", "verified", 1))
            connection.execute("INSERT INTO segments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                "segment-stale", "camera-1", "main", "hot-1", "camera-1/b.mp4", 10,
                "b" * 64, 2, "local", "verified", 2))
            connection.commit()
            connection.close()
            result = agent.catalog_batch(catalog, [{
                "cameraId": "camera-1", "profileId": "main", "generation": 3,
            }])
            self.assertEqual([item["segmentId"] for item in result], ["segment-1"])
            self.assertNotIn("endpoint", str(result).lower())


if __name__ == "__main__":
    unittest.main()
