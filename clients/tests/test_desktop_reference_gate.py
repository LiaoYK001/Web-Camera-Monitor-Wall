#!/usr/bin/env python3
"""Unit tests for the private v2-M2 desktop acceptance contract."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
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
            "maxRssGrowthMiB": 512,
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

    def test_rejects_unbounded_rss_growth(self) -> None:
        value = manifest()
        value["maxRssGrowthMiB"] = 4096
        with self.assertRaisesRegex(ValueError, "RSS growth"):
            gate.validate_manifest(value)

    def test_reads_current_process_rss(self) -> None:
        self.assertGreater(gate.process_rss_bytes(os.getpid()) or 0, 0)

    def test_peak_rss_growth_cannot_hide_mid_run_growth(self) -> None:
        self.assertEqual(gate.peak_rss_growth([100, 900, 120]), 800)

    def test_remote_control_requires_https(self) -> None:
        self.assertEqual(gate.validate_control_url("https://control.example.test:8443/base"),
                         "https://control.example.test:8443/base")
        self.assertEqual(gate.validate_control_url("http://127.0.0.1:8080/"),
                         "http://127.0.0.1:8080")
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            gate.validate_control_url("http://control.example.test:8080")
        with self.assertRaisesRegex(ValueError, "userinfo"):
            gate.validate_control_url("https://user:password@control.example.test")

    def test_control_credentials_are_an_indivisible_secret_pair(self) -> None:
        old_user = os.environ.get("WEBOBS_REFERENCE_CONTROL_USERNAME")
        old_password = os.environ.get("WEBOBS_REFERENCE_CONTROL_PASSWORD")
        try:
            os.environ["WEBOBS_REFERENCE_CONTROL_USERNAME"] = "operator"
            os.environ.pop("WEBOBS_REFERENCE_CONTROL_PASSWORD", None)
            with self.assertRaisesRegex(ValueError, "both required"):
                gate.validate_control_credentials()
            os.environ["WEBOBS_REFERENCE_CONTROL_PASSWORD"] = "private-password"
            self.assertEqual(gate.validate_control_credentials(),
                             ("operator", "private-password"))
        finally:
            for name, previous in (("WEBOBS_REFERENCE_CONTROL_USERNAME", old_user),
                                   ("WEBOBS_REFERENCE_CONTROL_PASSWORD", old_password)):
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous

    def test_private_evidence_must_stay_outside_repository_and_be_new(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the Git worktree"):
            gate.validate_evidence_path(gate.REPOSITORY_ROOT / "private.json")
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory).resolve() / "evidence.json"
            self.assertEqual(gate.validate_evidence_path(evidence), evidence)
            evidence.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                gate.validate_evidence_path(evidence)

    def test_referenced_credentials_must_exist_and_unrelated_values_are_scrubbed(self) -> None:
        value = manifest()
        old_user = os.environ.get("WEBOBS_PRIVATE_USER")
        old_password = os.environ.get("WEBOBS_PRIVATE_PASSWORD")
        old_unrelated = os.environ.get("WEBOBS_PRIVATE_UNRELATED")
        try:
            os.environ.pop("WEBOBS_PRIVATE_USER", None)
            os.environ.pop("WEBOBS_PRIVATE_PASSWORD", None)
            with self.assertRaisesRegex(ValueError, "are empty"):
                gate.private_environment(value)
            os.environ["WEBOBS_PRIVATE_USER"] = "user"
            os.environ["WEBOBS_PRIVATE_PASSWORD"] = "password"
            os.environ["WEBOBS_PRIVATE_UNRELATED"] = "do-not-forward"
            environment = gate.private_environment(value)
            self.assertEqual(environment["WEBOBS_PRIVATE_USER"], "user")
            self.assertNotIn("WEBOBS_PRIVATE_UNRELATED", environment)
        finally:
            for name, previous in (("WEBOBS_PRIVATE_USER", old_user),
                                   ("WEBOBS_PRIVATE_PASSWORD", old_password),
                                   ("WEBOBS_PRIVATE_UNRELATED", old_unrelated)):
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous

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
