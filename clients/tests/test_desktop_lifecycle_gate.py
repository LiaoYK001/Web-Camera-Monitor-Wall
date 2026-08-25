#!/usr/bin/env python3
"""Unit coverage for the private v2-M2 desktop lifecycle gate."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


MODULE = Path(__file__).with_name("run-desktop-lifecycle-gate.py")
SPEC = importlib.util.spec_from_file_location("desktop_lifecycle_gate", MODULE)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class DesktopLifecycleGateTests(unittest.TestCase):
    def test_helper_is_private_regular_and_silent(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the public worktree"):
            gate.validate_private_helper(MODULE)
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "helper"
            helper.write_text("fixture", encoding="utf-8")
            helper.chmod(0o700)
            self.assertEqual(gate.validate_private_helper(helper), helper.resolve())
            completed = subprocess.CompletedProcess([str(helper)], 0, "", "")
            with mock.patch.object(gate.subprocess, "run", return_value=completed), \
                    mock.patch.object(gate.time, "time", side_effect=[10.0, 13.0]):
                self.assertEqual(gate.run_private_helper(helper, 30), 3.0)
            noisy = subprocess.CompletedProcess([str(helper)], 0, "unsafe", "")
            with mock.patch.object(gate.subprocess, "run", return_value=noisy):
                with self.assertRaisesRegex(RuntimeError, "emitted unsafe output"):
                    gate.run_private_helper(helper, 30)

    def test_lifecycle_command_is_atomic_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "command"
            for command in ("active", "background", "foreground"):
                gate.atomic_command(target, command)
                self.assertEqual(target.read_text(encoding="utf-8"), command + "\n")
            with self.assertRaisesRegex(ValueError, "invalid"):
                gate.atomic_command(target, "arbitrary")

    def test_private_values_are_rejected_from_diagnostics(self) -> None:
        manifest = {"streams": [{"endpoint": "rtsp://camera.private.invalid/live"}]}
        previous = os.environ.get("WEBOBS_PRIVATE_TEST_TOKEN")
        try:
            os.environ["WEBOBS_PRIVATE_TEST_TOKEN"] = "private-fixture-token"
            gate.assert_no_private_output("bounded diagnostic", manifest)
            for value in (manifest["streams"][0]["endpoint"], "private-fixture-token"):
                with self.assertRaisesRegex(RuntimeError, "exposed"):
                    gate.assert_no_private_output("failure " + value, manifest)
        finally:
            if previous is None:
                os.environ.pop("WEBOBS_PRIVATE_TEST_TOKEN", None)
            else:
                os.environ["WEBOBS_PRIVATE_TEST_TOKEN"] = previous

    def test_production_probe_exposes_only_explicit_acceptance_hooks(self) -> None:
        main = (gate.ROOT / "clients/src/main.cpp").read_text(encoding="utf-8")
        pipeline = (gate.ROOT / "clients/src/media_pipeline.cpp").read_text(encoding="utf-8")
        batch = (gate.ROOT / "clients/src/batch_probe.cpp").read_text(encoding="utf-8")
        authorization = (gate.ROOT / "clients/src/client_auth_probe.cpp").read_text(
            encoding="utf-8")
        controller = (gate.ROOT / "clients/src/client_controller.cpp").read_text(
            encoding="utf-8")
        self.assertIn("probe-lifecycle-trigger", main)
        self.assertIn("probe-force-hardware-failure", main)
        self.assertIn("force_hardware_failure_for_acceptance", pipeline)
        self.assertIn("hardware_decoder_failed_software_fallback", pipeline)
        self.assertIn("lifecycle trigger must be a bounded absolute regular file", batch)
        self.assertIn("focusStreams()->attach(session_id, &probe_video_sink)", authorization)
        self.assertIn("offline-startup-ready", authorization)
        self.assertIn('state_ == QStringLiteral("offline-ready")', controller)


if __name__ == "__main__":
    unittest.main(verbosity=2)
