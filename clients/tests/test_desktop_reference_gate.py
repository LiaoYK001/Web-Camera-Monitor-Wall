#!/usr/bin/env python3
"""Unit tests for the private v2-M2 desktop acceptance contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("run-desktop-reference-gate.py")
SPEC = importlib.util.spec_from_file_location("desktop_reference_gate", MODULE_PATH)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def manifest() -> dict:
    streams = []
    for index in range(16):
        streams.append({
            "name": f"sub-{index + 1}", "role": "sub", "adapter": "rtsp",
            "endpoint": f"rtsp://camera-{index + 1}.invalid/sub", "codec": "h264",
            "expectedWidth": 640, "expectedHeight": 360, "expectedFps": 15,
            "usernameEnv": "WEBOBS_PRIVATE_USER",
            "passwordEnv": "WEBOBS_PRIVATE_PASSWORD",
        })
    streams.append({
        "name": "main", "role": "main", "adapter": "rtsp",
        "endpoint": "rtsp://camera-main.invalid/main", "codec": "h265",
        "expectedWidth": 1920, "expectedHeight": 1080, "expectedFps": 30,
        "usernameEnv": "WEBOBS_PRIVATE_USER",
        "passwordEnv": "WEBOBS_PRIVATE_PASSWORD",
    })
    return {"schemaVersion": 1, "durationSeconds": 1800, "maxDroppedPercent": 0.99,
            "requireHardware": True, "streams": streams}


class DesktopReferenceGateTests(unittest.TestCase):
    def test_accepts_exact_m2_shape(self) -> None:
        self.assertEqual(len(gate.validate_manifest(manifest())["streams"]), 17)

    def test_rejects_short_or_one_percent_gate(self) -> None:
        value = manifest()
        value["durationSeconds"] = 1799
        with self.assertRaisesRegex(ValueError, "1800-7200"):
            gate.validate_manifest(value)
        value = manifest()
        value["maxDroppedPercent"] = 1
        with self.assertRaisesRegex(ValueError, "below one"):
            gate.validate_manifest(value)

    def test_rejects_wrong_reference_resolution(self) -> None:
        value = manifest()
        value["streams"][0]["expectedWidth"] = 1280
        with self.assertRaisesRegex(ValueError, "640x360"):
            gate.validate_manifest(value)

    def test_server_media_comparison_covers_processes_and_rtsp(self) -> None:
        baseline = {"rtspSessions": 2, "engineActive": False,
                    "compositePublisherActive": False, "processes": [
            {"name": "mediamtx", "instances": 1}, {"name": "ffmpeg", "instances": 0}]}
        self.assertTrue(gate.same_server_media(baseline, baseline.copy()))
        changed = {**baseline, "rtspSessions": 3}
        self.assertFalse(gate.same_server_media(baseline, changed))
        changed = {**baseline, "processes": [
            {"name": "mediamtx", "instances": 1}, {"name": "ffmpeg", "instances": 1}]}
        self.assertFalse(gate.same_server_media(baseline, changed))
        changed = {**baseline, "engineActive": True}
        self.assertFalse(gate.same_server_media(baseline, changed))

    def test_private_endpoint_and_credentials_cannot_reach_logs(self) -> None:
        stream = manifest()["streams"][0]
        environment = {"WEBOBS_PRIVATE_USER": "private-user",
                       "WEBOBS_PRIVATE_PASSWORD": "private-password"}
        gate.assert_private_value_not_logged("bounded public diagnostic", stream, environment)
        for secret in (stream["endpoint"], "private-user", "private-password"):
            with self.assertRaisesRegex(RuntimeError, "private endpoint or credential"):
                gate.assert_private_value_not_logged(f"failure: {secret}", stream, environment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
