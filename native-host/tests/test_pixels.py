#!/usr/bin/env python3
"""Portable tests of the finite synthetic gate; NOT Windows pixel qualification."""
from __future__ import annotations
import json
import sys
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import pixel_windows as gate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class PixelContractTests(unittest.TestCase):
    def fixture_build(self, root):
        root.mkdir()
        (root / "webobs-native-pixel-test-build.json").write_text((HERE / "pixel-test-build.json").read_text())
        gate.write_new(root / "webobs-native-prototype.json", {"obsVersion": "32.1.2", "obsCommit": gate.OBS_COMMIT, "defaultProduct": False})

    def test_manifest_is_explicitly_nonredistributable_and_new_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime"
            self.fixture_build(runtime)
            gate.mark_build(runtime)
            manifest = gate.validate_build(runtime)
            for key in ("pixelTestBuild", "publicationForbidden"):
                self.assertIs(manifest[key], True)
            self.assertIs(manifest["redistributable"], False)
            with self.assertRaisesRegex(ValueError, "new staged"):
                gate.mark_build(runtime)
            (runtime / "webobs-native-pixel-test-build.json").unlink()
            with self.assertRaises(ValueError):
                gate.validate_build(runtime)

    def test_no_existing_config_can_be_marked(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime"
            self.fixture_build(runtime)
            (runtime / "config").mkdir()
            with self.assertRaisesRegex(ValueError, "new staged"):
                gate.mark_build(runtime)

    def state(self, seq):
        return {"schema": 1, "seq": seq, "phase": gate.PHASES[seq-1], "token": "a"*32, "pid": "123",
                "scope": "synthetic-test-only", "canvasWidth": 960, "canvasHeight": 540, "pixelQualified": False,
                "activeOutputs": 0, "activeEncoders": 0, "rawVideoActive": False, "sameInputPointersAndSettings": True,
                "globalFfmpegInputsIncludingPrivate": 0 if seq == 1 else 5, "studio": seq >= 3,
                "transitionStopped": seq >= 4, "programGeneration": 2 if seq == 5 else 1,
                "windows": [{"role": "main-preview", "qtClass": "OBSBasicPreview"}, {"role": "program-projector", "qtClass": "OBSProjector"}],
                "sources": [{"uuid": f"synthetic-{i}", "settingsSha256": str(i)*64} for i in range(5)] if seq > 1 else []}

    def test_phase_identity_uuid_counts_encoder_and_no_implicit_take(self):
        for seq in range(1,6):
            state = self.state(seq)
            gate.validate_state(state, seq, "a"*32, 123)
            for key, bad in (("seq", 6), ("token", "b"*32), ("pid", "124"), ("canvasWidth", 1920),
                             ("activeEncoders", 1), ("activeOutputs", 1), ("rawVideoActive", True),
                             ("globalFfmpegInputsIncludingPrivate", 6), ("sameInputPointersAndSettings", False),
                             ("programGeneration", 99), ("pixelQualified", True)):
                with self.subTest(seq=seq,key=key), self.assertRaises(AssertionError):
                    gate.validate_state(dict(state, **{key:bad}), seq, "a"*32, 123)
        bad = self.state(3)
        bad["windows"][0]["qtClass"] = "OBSProjector"
        with self.assertRaises(AssertionError):
            gate.validate_state(bad, 3, "a"*32, 123)
        bad = self.state(4)
        bad["sources"][1]["uuid"] = bad["sources"][0]["uuid"]
        with self.assertRaises(AssertionError):
            gate.validate_state(bad, 4, "a"*32, 123)

    def test_metadata_is_bounded_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "metadata.json"
            gate.write_new(path, {"schema":1})
            with self.assertRaises(FileExistsError):
                gate.write_new(path, {"schema":2})
            self.assertEqual(gate.read_json(path), {"schema":1})
            path.write_text(" "*65537)
            with self.assertRaises(ValueError):
                gate.read_json(path)

    @unittest.skipUnless(shutil.which("node"), "Node test tool unavailable")
    def test_geometry_timecode_and_negative_cases(self):
        subprocess.run([shutil.which("node"), str(HERE / "pixel-pattern.cjs"), "selftest"], check=True)

    @unittest.skipUnless(shutil.which("node"), "Node test tool unavailable")
    def test_all_eight_missing_or_bad_samples_are_reported_not_first_throw(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([shutil.which("node"), str(HERE / "pixel-pattern.cjs"), "analyze", directory,
                                     "program-projector", "forward", "true"], check=True, capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertFalse(report["passed"])
            self.assertEqual([sample["sample"] for sample in report["samples"]], list(range(8)))
            self.assertTrue(all(not sample["passed"] for sample in report["samples"]))
            self.assertNotIn(directory, json.dumps(report))
            self.assertNotIn('ENOENT:', json.dumps(report))
            self.assertFalse(report["temporalProgress"])
            # Preserve our fixed assertion diagnostics, but never filesystem paths.
            (Path(directory) / "client-0.bmp").write_bytes(b"BM")
            result = subprocess.run([shutil.which("node"), str(HERE / "pixel-pattern.cjs"), "analyze", directory,
                                     "program-projector", "forward", "true"], check=True, capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertIn("Invalid screenshot BMP", report["samples"][0]["error"])
            self.assertNotIn(directory, json.dumps(report))

    def test_build_and_harness_have_no_normal_product_entry_or_network(self):
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text()
        source = (ROOT / "native-host/src/pixel_test.cpp").read_text()
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text()
        builder = (ROOT / "desktop/scripts/build-obs-native.ps1").read_text()
        self.assertIn('option(WEBOBS_NATIVE_PIXEL_TEST "NON-REDISTRIBUTABLE synthetic final-window pixel test entry point" OFF)', cmake)
        self.assertIn("#ifdef WEBOBS_NATIVE_PIXEL_TEST", plugin)
        self.assertIn("if(WEBOBS_NATIVE_PIXEL_TEST)", cmake)
        for text in ("obs_enum_all_sources", "OBSBasicPreview", "OBSProjector", 'ack.size() == 3', 'request.size() != 2',
                     '"/claimed.json"', "240000", 'obs_frontend_open_projector("StudioProgram"', "obs_frontend_preview_program_trigger_transition"):
            self.assertIn(text, source)
        for text in ("QTcpServer", "QWebSocket", "obs_frontend_recording_start", "obs_output_start", "obs_frontend_take_screenshot", "gs_stage_texture"):
            self.assertNotIn(text, source)
        self.assertIn('[switch]$PixelTest', builder)
        self.assertIn('--mark-build', builder)
        self.assertIn('-DWEBOBS_NATIVE_PIXEL_TEST=$pixelBuild', builder)
        self.assertIn("$SmokeTest -and $PixelTest", builder)

    @unittest.skipUnless(os.environ.get("WEBOBS_TEST_FFMPEG") and shutil.which("node"), "Opt-in local FFmpeg fixture smoke")
    def test_real_five_independent_hevc_preencoding(self):
        ffmpeg = Path(os.environ["WEBOBS_TEST_FFMPEG"])
        ffprobe = ffmpeg.with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = gate.make_fixtures(Path(temporary), ffmpeg, ffprobe, shutil.which("node"))
            self.assertEqual(len(fixtures), 5)
            self.assertEqual(len({f["sha256"] for f in fixtures}),5)
            self.assertEqual(len(list(Path(temporary).glob("*.mkv"))),5)
            self.assertEqual(list(Path(temporary).glob("*.rgb")),[])


if __name__ == "__main__":
    import sys
    unittest.main(verbosity=2)
