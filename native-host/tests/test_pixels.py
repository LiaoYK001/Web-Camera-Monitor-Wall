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
import smoke_windows as smoke

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
                "wallReuseVerified": seq >= 2,
                "productBootstrapVerified": seq >= 6,
                "globalFfmpegInputsIncludingPrivate": 0 if seq == 1 else 10 if seq >= 6 else 5,
                "studio": 3 <= seq <= 5, "transitionStopped": 4 <= seq <= 5, "programGeneration": 2 if seq >= 5 else 1,
                "windows": ([{"role": "main-preview", "qtClass": "OBSBasicPreview"}] if seq >= 6 else
                            [{"role": "main-preview", "qtClass": "OBSBasicPreview"}, {"role": "program-projector", "qtClass": "OBSProjector"}]),
                "sources": [{"uuid": f"synthetic-{i}", "settingsSha256": str(i)*64} for i in range(5)] if seq > 1 else []}

    def test_phase_identity_uuid_counts_encoder_and_no_implicit_take(self):
        for seq in range(1,7):
            state = self.state(seq)
            gate.validate_state(state, seq, "a"*32, 123)
            for key, bad in (("seq", 1 if seq == 6 else 6), ("token", "b"*32), ("pid", "124"), ("canvasWidth", 1920),
                             ("activeEncoders", 1), ("activeOutputs", 1), ("rawVideoActive", True),
                             ("globalFfmpegInputsIncludingPrivate", 6), ("sameInputPointersAndSettings", False),
                             ("programGeneration", 99), ("pixelQualified", True), ("wallReuseVerified", False),
                             ("productBootstrapVerified", False)):
                if key == "wallReuseVerified" and seq < 2:
                    continue
                if key == "productBootstrapVerified" and seq < 6:
                    continue
                with self.subTest(seq=seq,key=key), self.assertRaises(AssertionError):
                    gate.validate_state(dict(state, **{key:bad}), seq, "a"*32, 123)
        # The loopback RTSP phase keeps ten global inputs (five local media plus
        # five RTSP inputs) and leaves Studio again once Program closed.
        for change in ({"globalFfmpegInputsIncludingPrivate": 5}, {"studio": True},
                       {"sources": self.state(6)["sources"][:4]},
                       {"windows": self.state(5)["windows"]}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                gate.validate_state(dict(self.state(6), **change), 6, "a"*32, 123)
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
        for text in ("obs_enum_all_sources", "OBSBasicPreview", "OBSProjector", 'ack.size() == 3', 'request.size() != 3',
                     '"/claimed.json"', "240000", 'obs_frontend_open_projector("StudioProgram"', "obs_frontend_preview_program_trigger_transition",
                     "loopback_rtsp_urls", "create_rtsp"):
            self.assertIn(text, source)
        gate_source = (ROOT / "native-host/tests/pixel_windows.py").read_text()
        for text in ("LoopbackRtsp", "rtsp-loopback", "mediamtx", "rtsp_transport", "loopbackRtspPhaseQualified"):
            self.assertIn(text, gate_source)
        self.assertEqual(gate.PHASES[-1], "rtsp-loopback")
        for text in ("QTcpServer", "QWebSocket", "obs_frontend_recording_start", "obs_output_start", "obs_frontend_take_screenshot", "gs_stage_texture"):
            self.assertNotIn(text, source)
        self.assertIn('[switch]$PixelTest', builder)
        self.assertIn('--mark-build', builder)
        self.assertIn('-DWEBOBS_NATIVE_PIXEL_TEST=$pixelBuild', builder)
        self.assertIn("$SmokeTest -and $PixelTest", builder)

    def capture_result(self, failed=False):
        roles = [{"role": role, "captureFailed": False, "sampleCount": 8,
                  "sampleElapsedMs": [400+i*310 for i in range(8)]} for role in gate.CAPTURE_ROLES]
        if failed:
            roles[0].update(captureFailed=True, sampleCount=0, sampleElapsedMs=[],
                            diagnostic={"stage": "identity", "code": "process-identity", "sampleIndex": -1,
                                        "completedSamples": 0, "nativeError": 0, "compilerCodes": []})
        return {"schema": 1, "captureFailed": failed, "captures": roles}

    def test_capture_report_retains_safe_partial_failures_and_all_eight_counts(self):
        for failed in (False, True):
            payload = self.capture_result(failed)
            # A private subprocess must not smuggle extra data into the artifact.
            payload.update(token="secret-token", pid="777777", hwnd="deadbeef", path="C:/private/profile")
            payload["captures"][0]["privateError"] = "C:/private/profile secret-token"
            report = gate.capture_report(subprocess.CompletedProcess([], int(failed), json.dumps(payload), "private-stderr"))
            self.assertEqual(report["captureFailed"], failed)
            self.assertEqual(len(report["captures"]), 2)
            self.assertEqual(report["captures"][1]["sampleCount"], 8)
            if failed:
                self.assertEqual(report["captures"][0]["diagnostic"]["code"], "process-identity")
            for secret in ("secret-token", "777777", "deadbeef", "C:/private", "private-stderr"):
                self.assertNotIn(secret, json.dumps(report))

    def test_capture_compile_failure_keeps_codes_not_stderr_or_paths(self):
        payload = {"schema": 1, "captureFailed": True, "captures": [],
                   "diagnostic": {"stage": "compile", "code": "csharp-compilation", "compilerCodes": ["CS1069", "CS0012"]}}
        report = gate.capture_report(subprocess.CompletedProcess([], 1, json.dumps(payload), "C:/private/token user HWND123"))
        self.assertEqual(report["diagnostic"]["stage"], "compile")
        self.assertEqual(report["diagnostic"]["compilerCodes"], ["CS0012", "CS1069"])
        self.assertNotIn("private", json.dumps(report))
        # Parser/host failures before the script's catch still have a bounded
        # category; only the exact compiler-code grammar may leave stderr.
        report = gate.capture_report(subprocess.CompletedProcess([], 1, "", "C:/private/token: CS1069 PID777 HWND123"))
        self.assertEqual(report["diagnostic"]["code"], "no-report")
        self.assertEqual(report["diagnostic"]["compilerCodes"], ["CS1069"])
        for secret in ("private", "token", "777", "HWND123"):
            self.assertNotIn(secret, json.dumps(report))

    def test_capture_report_rejects_unsafe_or_inconsistent_categories(self):
        for bad in ({}, {"schema": 1, "captureFailed": False, "captures": []},
                    {"schema": 1, "captureFailed": True, "captures": [], "diagnostic": {"stage": "private-path", "code": "secret"}}):
            report = gate.capture_report(subprocess.CompletedProcess([], 0, json.dumps(bad), ""))
            self.assertTrue(report["captureFailed"])
            self.assertEqual(report["diagnostic"]["code"], "invalid-report")
            self.assertNotIn("private-path", json.dumps(report))
        for change in ({"sampleCount": 7}, {"sampleElapsedMs": [999999]*8},
                       {"role": "C:/private/path"}, {"captureFailed": "false"}):
            payload = self.capture_result()
            payload["captures"][0].update(change)
            report = gate.capture_report(subprocess.CompletedProcess([], 0, json.dumps(payload), ""))
            self.assertTrue(report["captureFailed"])
        for value in (-2, 8, "secret"):
            payload = self.capture_result(True)
            payload["captures"][0]["diagnostic"]["sampleIndex"] = value
            self.assertTrue(gate.capture_report(subprocess.CompletedProcess([], 1, json.dumps(payload), ""))["captureFailed"])
            self.assertEqual(gate.capture_report(subprocess.CompletedProcess([], 1, json.dumps(payload), ""))["diagnostic"]["code"], "invalid-report")

    def test_capture_timeout_and_launch_failure_are_bounded_without_private_command(self):
        command = ["C:/private/tool", "secret-token", "PID777", "HWND123"]
        for failure, code in ((subprocess.TimeoutExpired(command, 45, output="secret", stderr="C:/private"), "timeout"),
                              (OSError("C:/private/secret-token"), "launch-failed")):
            with patch.object(gate.subprocess, "run", side_effect=failure):
                report = gate.run_capture(command, 45)
                self.assertTrue(report["captureFailed"])
                self.assertEqual(report["diagnostic"]["code"], code)
                for secret in command + ["secret-token", "PID777", "HWND123"]:
                    self.assertNotIn(secret, json.dumps(report))

    def test_capture_compile_only_references_and_unchanged_identity_guards(self):
        script = (HERE / "capture-pixels.ps1").read_text()
        self.assertIn("[switch]$CompileOnly", script)
        # Core-only GDI P/Invoke: no Windows Drawing/Forms assembly loading.
        self.assertIn("Add-Type -ErrorVariable compilerErrors -TypeDefinition $typeDefinition", script)
        self.assertNotIn("System.Drawing", script)
        self.assertNotIn("System.Windows.Forms", script)
        for gdi in ("CreateCompatibleDC", "CreateCompatibleBitmap", "BitBlt", "GetDIBits", "GetSystemMetrics"):
            self.assertIn(gdi, script)
        # Fixed .NET type/assembly names only for CS0012/CS1069 diagnosis.
        self.assertIn("missingTypes", script)
        self.assertIn("missingAssemblies", script)
        for guard in ("process.StartTime.ToUniversalTime().ToFileTimeUtc()!=creation", "actual!=pid || actualRoot!=pid",
                      "GetAncestor(hwnd,2)!=root", "!IsChild(hwnd,hit)", "origin.x+width>screenWidth", "DwmFlush()", "i<8"):
            self.assertIn(guard, script)
        self.assertNotIn("Exception.Message", script.replace("# Never emit Exception.Message", ""))

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Real PowerShell inline C# compile preflight requires Windows")
    def test_real_windows_capture_compile_only(self):
        completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(HERE / "capture-pixels.ps1"), "-CompileOnly"],
                                   capture_output=True, text=True, timeout=30)
        # Never echo the compiler's unbounded stderr on test failure.
        self.assertEqual(completed.returncode, 0, "Inline capture C# compile preflight failed")
        value = json.loads(completed.stdout)
        self.assertEqual(value, {"schema": 1, "compileOnly": True, "captureFailed": False, "captures": []})

    @unittest.skipUnless(os.environ.get("WEBOBS_TEST_FFMPEG") and shutil.which("node"), "Opt-in local FFmpeg fixture smoke")
    def test_real_five_independent_mixed_codec_preencoding(self):
        ffmpeg = Path(os.environ["WEBOBS_TEST_FFMPEG"])
        ffprobe = ffmpeg.with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = gate.make_fixtures(Path(temporary), ffmpeg, ffprobe, shutil.which("node"))
            self.assertEqual(len(fixtures), 5)
            self.assertEqual(len({f["sha256"] for f in fixtures}),5)
            self.assertEqual({f["codec"] for f in fixtures}, {"hevc", "h264"})
            self.assertEqual(len(list(Path(temporary).glob("*.mkv"))),5)
            self.assertEqual(list(Path(temporary).glob("*.rgb")),[])


class ProductSmokeContractTests(unittest.TestCase):
    def test_payload_has_five_bounded_cameras(self):
        payload = smoke.product_config_payload()
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(len(payload["cameras"]), 5)
        for index, camera in enumerate(payload["cameras"], start=1):
            self.assertEqual(camera["id"], f"cam-{index}")
            self.assertTrue(camera["url"].startswith("rtsp://127.0.0.1:9/"))
            self.assertIs(camera["hardwareDecode"], False)

    def test_receipt_accepts_a_clean_bootstrap(self):
        receipt = {"schema": 1, "scope": "product-cameras", "ok": True, "created": 5, "reused": 0,
                   "sceneReused": False, "canvasApplied": False, "items": 5}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "product-bootstrap.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            parsed = smoke.check_product_receipt(path)
        self.assertEqual(parsed["created"], 5)

    def test_receipt_rejects_errors_and_leaks(self):
        base = {"schema": 1, "scope": "product-cameras", "ok": True, "created": 5, "reused": 0,
                "sceneReused": False, "canvasApplied": False, "items": 5}
        cases = [dict(base, error="camera-name-conflict"), dict(base, created=4), dict(base, ok=False),
                 dict(base, items=4), dict(base, leaked="rtsp://127.0.0.1:9/smoke-1")]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "product-bootstrap.json"
                path.write_text(json.dumps(case), encoding="utf-8")
                with self.assertRaises(AssertionError):
                    smoke.check_product_receipt(path)


if __name__ == "__main__":
    import sys
    unittest.main(verbosity=2)
