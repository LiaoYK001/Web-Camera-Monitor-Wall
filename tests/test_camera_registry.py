#!/usr/bin/env python3
"""Deterministic Camera Registry and NVR reference contract tests."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


registry = load_module("webobs_camera_registry_test", Path(os.environ.get(
    "WEBOBS_TEST_CAMERA_REGISTRY", ROOT / "camera" / "camera_registry.py")))
nvr = load_module("webobs_nvr_test", Path(os.environ.get(
    "WEBOBS_TEST_NVR_SERVICE", ROOT / "nvr" / "nvr_service.py")))


class CameraRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="webobs-camera-tests-")
        registry.DB_PATH = Path(self.temporary.name) / "cameras.db"
        registry.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sqlite_wal_and_stable_profile_contract(self) -> None:
        camera = registry.validate_camera({
            "id": "front-door",
            "name": "Front Door",
            "address": "rtsp://camera.example.invalid/live",
            "adapter": "rtsp",
            "credentialsRef": "front-door",
            "hardwareDecode": "auto",
            "profiles": [{
                "id": "main", "name": "Main", "role": "main",
                "endpoint": "rtsp://camera.example.invalid/live",
                "videoCodec": "h264", "audioCodec": "aac",
                "width": 1920, "height": 1080, "fps": 25,
            }],
            "capabilities": {"ptz": False},
        })
        stored = registry.save_camera(camera, False)
        self.assertEqual(stored["id"], "front-door")
        self.assertEqual(stored["profiles"][0]["videoCodec"], "h264")
        self.assertNotIn("password", str(stored).lower())
        with registry.connect() as database:
            self.assertEqual(database.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_embedded_credentials_and_secret_queries_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            registry.safe_endpoint(
                "rtsp" + "://operator:secret@camera.example.invalid/live", "rtsp"
            )
        with self.assertRaises(ValueError):
            registry.safe_endpoint("https://camera.example.invalid/live?access_token=secret", "hls")
        with self.assertRaises(ValueError):
            registry.validate_camera({
                "name": "Unsafe", "address": "rtsp://camera.example.invalid/live",
                "adapter": "rtsp", "credentialsRef": "../escape", "profiles": [],
            })

    def test_nvr_accepts_registry_ids_without_raw_urls(self) -> None:
        configuration = nvr.validate_config({
            "schemaVersion": 1,
            "cameras": [{
                "id": "front-door-archive", "name": "Front Door", "policy": "continuous",
                "cameraId": "front-door", "mainProfileId": "main", "stream": "main",
            }],
        })
        camera = configuration["cameras"][0]
        self.assertEqual(camera["cameraId"], "front-door")
        self.assertEqual(camera["mainUrl"], "")
        with self.assertRaises(nvr.ConfigError):
            nvr.validate_config({
                "schemaVersion": 1,
                "cameras": [{
                    "id": "mixed", "name": "Mixed", "cameraId": "front-door",
                    "mainProfileId": "main", "mainUrl": "rtsp://camera.example.invalid/live",
                }],
            })


if __name__ == "__main__":
    unittest.main()
