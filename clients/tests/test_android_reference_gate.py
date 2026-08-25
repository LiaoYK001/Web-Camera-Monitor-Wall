#!/usr/bin/env python3
"""Regression tests for the private v2-M3 Android evidence parser."""

from __future__ import annotations

import importlib.util
import unittest
from unittest import mock
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

    def test_wifi_state_parser_is_fail_closed(self) -> None:
        with mock.patch.object(MODULE, "adb", return_value="Wi-Fi is enabled"):
            self.assertTrue(MODULE.wifi_enabled("fixture"))
        with mock.patch.object(MODULE, "adb", return_value="Wi-Fi is disabled"):
            self.assertFalse(MODULE.wifi_enabled("fixture"))
        with mock.patch.object(MODULE, "adb", return_value="unsupported"), \
                mock.patch.object(MODULE, "android_setting", return_value="unexpected"):
            self.assertIsNone(MODULE.wifi_enabled("fixture"))

    def test_package_probe_requires_a_real_package_path(self) -> None:
        with mock.patch.object(MODULE, "adb", return_value="package:/data/app/base.apk\n"):
            self.assertTrue(MODULE.package_installed("fixture", MODULE.PACKAGE))
        with mock.patch.object(MODULE, "adb", return_value=""):
            self.assertFalse(MODULE.package_installed("fixture", MODULE.PACKAGE))

    def test_all_streams_must_report_reconnected(self) -> None:
        documents = [{"result": "reconnected", "name": "one"},
                     {"result": "reconnected", "name": "two"}]
        with mock.patch.object(MODULE, "log_documents", return_value=("", documents)):
            _, observed = MODULE.wait_for_reconnections(
                "fixture", {"one", "two"}, MODULE.time.monotonic() + 1)
        self.assertEqual(observed, {"one", "two"})

    def test_device_matrix_commands_and_evidence_are_mandatory(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for required in ("accelerometer_rotation", "KEYCODE_SLEEP", "svc\", \"wifi",
                         "microphone-permission", "wifiReconnectMilliseconds",
                         "lockScreenReleaseMilliseconds", "rotationsTested",
                         "foreground-resumed", "foregroundResumeWallMilliseconds",
                         "dedicated reference device", "uninstall\", PACKAGE"):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
