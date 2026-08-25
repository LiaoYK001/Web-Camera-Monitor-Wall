#!/usr/bin/env python3
"""Regression tests for the private v2-M3 Android evidence parser."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run-android-reference-gate.py")
SPEC = importlib.util.spec_from_file_location("android_reference_gate", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def manifest() -> dict:
    return {"schemaVersion": 1, "durationSeconds": 1800, "maxDroppedPercent": 1.999,
            "maxThermalStatus": 2,
            "streams": [{"name": f"camera-{index}", "adapter": "rtsp",
                         "endpoint": f"rtsp://192.0.2.{index + 1}/sub", "codec": "h264",
                         "expectedWidth": 640, "expectedHeight": 360, "expectedFps": 15,
                         "usernameEnv": "", "passwordEnv": ""}
                        for index in range(9)]}


class AndroidReferenceGateTests(unittest.TestCase):
    def test_exact_nine_stream_30_minute_contract_passes(self) -> None:
        self.assertEqual(len(MODULE.validate_manifest(manifest())["streams"]), 9)

    def test_severe_thermal_allowance_is_rejected(self) -> None:
        value = manifest()
        value["maxThermalStatus"] = 3
        with self.assertRaises(ValueError):
            MODULE.validate_manifest(value)

    def test_two_percent_drop_limit_is_exclusive(self) -> None:
        value = manifest()
        value["maxDroppedPercent"] = 2
        with self.assertRaises(ValueError):
            MODULE.validate_manifest(value)

    def test_credentials_and_non_substream_shapes_are_rejected(self) -> None:
        value = manifest()
        value["streams"][0]["usernameEnv"] = "WEBOBS_PRIVATE_USER"
        with self.assertRaises(ValueError):
            MODULE.validate_manifest(value)
        value = manifest()
        value["streams"][0]["expectedWidth"] = 1920
        with self.assertRaises(ValueError):
            MODULE.validate_manifest(value)

    def test_userinfo_endpoint_is_rejected(self) -> None:
        value = manifest()
        value["streams"][0]["endpoint"] = "rtsp://" + "fixture-user:fixture-secret@192.0.2.1/sub"
        with self.assertRaises(ValueError):
            MODULE.validate_manifest(value)


if __name__ == "__main__":
    unittest.main()
