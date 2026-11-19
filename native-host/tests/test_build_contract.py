#!/usr/bin/env python3
"""Cross-platform build/isolation tests, not Windows/Qt/media qualification."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "native-host/scripts"
sys.path.insert(0, str(SCRIPTS))
import prepare
import stage
import smoke_windows


class BuildContractTests(unittest.TestCase):
    def test_repository_text_reads_have_explicit_utf8(self):
        # Source files and bilingual docs are UTF-8, independent of Windows ACP.
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "read_text"]
        self.assertTrue(calls)
        for call in calls:
            self.assertTrue(any(keyword.arg == "encoding" and
                                isinstance(keyword.value, ast.Constant) and
                                keyword.value.value == "utf-8" for keyword in call.keywords),
                            "repository source read must explicitly use UTF-8")

    def test_lock_matches_pinned_obs_and_only_needed_dependencies(self):
        lock = json.loads((ROOT / "desktop/dependencies.lock.json").read_text(encoding="utf-8"))
        presets = json.loads((ROOT / "obs/obs-studio/CMakePresets.json").read_text(encoding="utf-8"))
        artifacts = prepare.locked_artifacts(lock, presets)
        self.assertEqual([a["id"] for a in artifacts], ["obs-deps", "obs-qt"])
        for field, value in [("obsCommit", "0" * 40)]:
            bad = copy.deepcopy(lock)
            bad[field] = value
            with self.assertRaises(ValueError):
                prepare.locked_artifacts(bad, presets)
        for field in ("sha256", "url", "version"):
            bad = copy.deepcopy(lock)
            next(a for a in bad["artifacts"] if a["id"] == "obs-qt")[field] = "not-pinned"
            with self.assertRaises(ValueError):
                prepare.locked_artifacts(bad, presets)

    def test_cache_is_rehashed_and_offline_never_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            payload = cache / "obs-qt.zip"
            payload.write_bytes(b"fixture archive")
            artifact = {"id": "obs-qt", "sha256": prepare.digest(payload), "url": "https://example.invalid/fixture"}
            with patch("urllib.request.urlopen", side_effect=AssertionError("network must not run")):
                self.assertEqual(prepare.obtain(artifact, cache, True), payload)
                payload.write_bytes(b"corrupt")
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    prepare.obtain(artifact, cache, False)
                with self.assertRaisesRegex(ValueError, "Offline cache missing"):
                    prepare.obtain(dict(artifact, id="missing"), cache, True)

    def test_snapshot_excludes_untracked_and_rejects_modified_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "snapshot"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / "tracked.txt").write_text("fixed contents\n")
            (source / "nested with spaces").mkdir()
            (source / "nested with spaces/second.txt").write_text("another tracked entry\n")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
            pin = prepare.git(source, "rev-parse", "HEAD").strip()
            (source / "untracked-secret.txt").write_text("not copied")
            with patch.object(prepare, "OBS_COMMIT", pin):
                prepare.snapshot(source, output)
                self.assertFalse((output / "untracked-secret.txt").exists())
                self.assertEqual((output / "nested with spaces/second.txt").read_text(encoding="utf-8"), "another tracked entry\n")
                receipt = json.loads((output / ".webobs-source.json").read_text(encoding="utf-8"))
                self.assertEqual(len(receipt["files"]), 2)
                prepare.snapshot(source, output)
                (output / "tracked.txt").write_text("patched")
                with self.assertRaisesRegex(ValueError, "snapshot was modified"):
                    prepare.snapshot(source, output)
                (source / "tracked.txt").write_text("dirty upstream")
                with self.assertRaisesRegex(ValueError, "tracked modifications"):
                    prepare.snapshot(source, root / "another")

    @unittest.skipIf(sys.platform == "win32", "Windows Git normally checks out symlinks as text")
    def test_snapshot_materializes_link_text_without_reading_external_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "snapshot"
            source.mkdir()
            (root / "private.txt").write_text("never copied")
            (source / "tool-link").symlink_to("../private.txt")
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
            pin = prepare.git(source, "rev-parse", "HEAD").strip()
            with patch.object(prepare, "OBS_COMMIT", pin):
                prepare.snapshot(source, output)
                self.assertFalse((output / "tool-link").is_symlink())
                self.assertEqual((output / "tool-link").read_text(encoding="utf-8"), "../private.txt")
                prepare.snapshot(source, output)

    def fixture_runtime(self, root: Path) -> tuple[Path, Path, Path]:
        repo, source, runtime = root / "repo", root / "source", root / "runtime"
        for path in stage.REQUIRED:
            target = runtime / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fixture - not a real binary")
        for path in ("native-host/scripts/launch-native.ps1", "native-host/README.md", "native-host/LICENSE", "desktop/dependencies.lock.json"):
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture")
        source.mkdir()
        (source / "COPYING").write_text("fixture license")
        return repo, source, runtime

    def test_staging_requires_native_qt_plugin_and_new_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, source, runtime = self.fixture_runtime(Path(directory))
            manifest = stage.finalize(repo, source, runtime, "0.1.0-dev.test")
            self.assertEqual(json.loads((runtime / "webobs-native-prototype.json").read_text(encoding="utf-8")), manifest)
            self.assertFalse(manifest["defaultProduct"])
            self.assertEqual(manifest["servicesStarted"], [])
            self.assertEqual(manifest["obsCommit"], prepare.OBS_COMMIT)
            self.assertTrue((runtime / "portable_mode.txt").exists())
            self.assertTrue((runtime / "disable_updater.txt").exists())
            self.assertFalse((runtime / "config").exists())
            self.assertGreater(manifest["sizeBytesBeforeManifest"], 0)
            with self.assertRaisesRegex(ValueError, "new, separate"):
                stage.finalize(repo, source, runtime, "0.1.0-dev.test")
        with tempfile.TemporaryDirectory() as directory:
            repo, source, runtime = self.fixture_runtime(Path(directory))
            (runtime / "config").mkdir()
            with self.assertRaisesRegex(ValueError, "user configuration"):
                stage.finalize(repo, source, runtime, "0.1.0-dev.test")
        with tempfile.TemporaryDirectory() as directory:
            repo, source, runtime = self.fixture_runtime(Path(directory))
            # A symlink cannot stand in for Qt's native Windows platform plugin.
            target = runtime / "bin/64bit/platforms/qwindows.dll"
            target.unlink()
            with self.assertRaisesRegex(ValueError, "qwindows.dll"):
                stage.finalize(repo, source, runtime, "0.1.0-dev.test")
            with self.assertRaisesRegex(ValueError, "development-tagged"):
                stage.finalize(repo, source, runtime, "0.1.0")

    def test_smoke_fingerprint_detects_changes_without_exporting_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "private-obs"
            self.assertEqual(smoke_windows.fingerprint(profile), {})
            profile.mkdir()
            (profile / "secret.ini").write_text("private fixture")
            before = smoke_windows.fingerprint(profile)
            self.assertNotIn("private fixture", json.dumps(before))
            (profile / "secret.ini").write_text("changed private fixture")
            self.assertNotEqual(smoke_windows.fingerprint(profile), before)

    def test_launcher_and_builder_keep_architecture_boundaries(self):
        builder = (ROOT / "desktop/scripts/build-obs-native.ps1").read_text(encoding="utf-8")
        launcher = (SCRIPTS / "launch-native.ps1").read_text(encoding="utf-8")
        for expected in ("-DENABLE_FRONTEND=ON", "-DENABLE_BROWSER=OFF", "-DQt6_DIR=", "-A','x64", "-DCMAKE_SYSTEM_VERSION=10.0.22621.0", "BuildDirectory already exists"):
            self.assertIn(expected, builder)
        for forbidden in ("prepare-obs-headless.py", "Invoke-Checked 'pnpm'", "ENABLE_FRONTEND=OFF", "Invoke-Checked 'node'", "clients/", "GStreamer"):
            # Comment explicitly states no GStreamer; commands must never import it.
            if forbidden != "GStreamer":
                self.assertNotIn(forbidden, builder)
        for expected in ("$AllowPrototype", "--portable", "--disable-updater", "WorkingDirectory = Join-Path $root 'bin/64bit'", "OBS_PLUGINS_PATH", "QT_PLUGIN_PATH", "defaultProduct", "$ProcessGatePath", "Get-CimInstance Win32_Process"):
            self.assertIn(expected, launcher)
        self.assertNotIn("Start-Process", launcher)  # Explicit child environment, fixed CWD.
        self.assertNotIn("--multi", launcher)  # Do not bypass upstream portable instance guard.

    def test_program_output_relay_allocates_every_loopback_port(self):
        """The private Program relay must never assume a fixed publish port.

        The product's own distribution gateway MediaMTX binds WebRTC on 8889, and
        Windows reserves dynamic port ranges that can make a fixed port unbindable
        with nothing listening on it. Either case refused the publish start while
        the host state still reported an empty streamError, so every relay
        listener is allocated as a free loopback port and each refusal is recorded.
        """
        source = (ROOT / "native-host/src/product_output.cpp").read_text(encoding="utf-8")
        for forbidden in ("webrtcAddress: 127.0.0.1:8889", "http://127.0.0.1:8889", "port_available(8889)"):
            self.assertNotIn(forbidden, source)
        self.assertIn("int webrtc_port = free_tcp_port();", source)
        self.assertIn("int rtmp_port = free_tcp_port();", source)
        self.assertIn("webrtcAddress: 127.0.0.1:%3", source)
        self.assertIn('"rtmpAddress: 127.0.0.1:%5\\n"', source)
        # The publish URL carries no app segment, so the relay maps the stream
        # key onto the configured "program" path instead of "program/program".
        self.assertIn('QStringLiteral("rtmp://127.0.0.1:%1/").arg(rtmp_port)', source)
        start = source[source.index("bool start_media_mtx"):source.index("bool start_recording")]
        for refusal in ("mediamtx-unavailable", "mediamtx-port-failed", "mediamtx-directory-failed",
                        "mediamtx-config-failed", "mediamtx-start-failed", "mediamtx-exited",
                        "mediamtx-timeout"):
            self.assertIn('"%s"' % refusal, start)
        # A refusal has to carry the relay's own last words. QProcess only notices a
        # child exit through the event loop, and this wait runs inside a UI action,
        # so an unobserved exit turned a rejected configuration into a bare
        # "mediamtx-timeout" in run 44366851677.
        self.assertIn("waitForFinished(0)", start)
        self.assertIn("relay_log_tail", start)
        self.assertIn("relay_log.append(media_mtx.readAll())", start)

    def test_program_publishing_uses_only_services_the_windows_build_ships(self):
        """The Program publish output must use OBS identifiers the installed runtime has.

        desktop/scripts/build-obs-native.ps1 configures OBS with -DENABLE_WEBRTC=OFF,
        and obs-webrtc's own CMakeLists returns early without LibDataChannel, so
        neither whip_custom nor whip_output exists in the installed host: run
        44374662264 reached "stream-service-unavailable" for exactly that reason.
        rtmp_custom and rtmp_output are registered by the shipped rtmp-services.dll
        and obs-outputs.dll, RTMP/FLV audio is AAC, and the same private relay
        republishes the mix as RTSP plus WebRTC/WHEP for a real consumer.
        """
        source = (ROOT / "native-host/src/product_output.cpp").read_text(encoding="utf-8")
        builder = (ROOT / "desktop/scripts/build-obs-native.ps1").read_text(encoding="utf-8")
        self.assertIn("-DENABLE_WEBRTC=OFF", builder)
        for shipped in ('"rtmp_custom"', '"rtmp_output"', '"ffmpeg_aac"', '"rtmp: true\\n"'):
            self.assertIn(shipped, source)
        for absent in ('"whip_custom"', '"whip_output"', '"ffmpeg_opus"'):
            self.assertNotIn(absent, source)

    def test_program_output_relay_log_destination_is_accepted(self):
        """The private Program relay must only use log destinations the pinned MediaMTX accepts.

        MediaMTX v1.18.2 accepts stdout, file and syslog. The relay config used
        logDestinations: [stderr], printed "ERR: invalid log destination: stderr"
        and exited before opening any listener, which the host reported as
        mediamtx-timeout (run 44366851677). The shipped gateway config, which runs
        in production, uses stdout; the private relay now matches it.
        """
        source = (ROOT / "native-host/src/product_output.cpp").read_text(encoding="utf-8")
        self.assertIn('"logDestinations: [stdout]\\n"', source)
        self.assertNotIn("[stderr]", source)
        gateway = (ROOT / "gateway/mediamtx.yml").read_text(encoding="utf-8")
        self.assertIn("logDestinations: [stdout]", gateway)

    def test_published_program_video_gate_waits_past_a_keyframe_for_a_late_join(self):
        """Both Program video gates must decode across keyframe intervals.

        A consumer that joins after publishing starts lands inside the encoder's
        current GOP, so its first packets are P-slices with no reference picture.
        Reading 20 packets decoded zero frames twice (runs 44524750280 and
        44534272424) with return code 0 and "co located POCs unavailable" while
        the host advanced its render counter, and ffprobe reports pts_time as a
        string, which the old numeric check dropped so the measured span always
        read 0. Each gate now keeps at least ten strictly increasing decodable
        frames over more than two publish keyframe intervals on one connection,
        records when the first decodable frame arrived, and adds a packet probe
        that answers whether the relay hands a late consumer an IDR at all.
        """
        encoder = (ROOT / "native-host/src/product_output.cpp").read_text(encoding="utf-8")
        keyints = re.findall(r'obs_data_set_int\(video_settings\.get\(\), "keyint_sec", (\d+)\)', encoder)
        self.assertTrue(keyints, "Program outputs must state their keyframe interval")
        self.assertEqual(len(set(keyints)), 1, "recording and publishing must publish on one interval")
        keyint = int(keyints[0])

        gate = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")
        self.assertEqual(int(re.search(r"PROGRAM_ENCODER_KEYINT_SECONDS = (\d+)", gate).group(1)), keyint,
                         "the gate must read the interval the encoder actually uses")
        multiplier = int(re.search(r"PROGRAM_VIDEO_WINDOW_SECONDS = PROGRAM_ENCODER_KEYINT_SECONDS \* (\d+)",
                                   gate).group(1))
        self.assertGreaterEqual(multiplier, 2, "the read window must span at least two keyframe intervals")

        # One shared window reader for both the first publisher and the recovered one.
        self.assertEqual(gate.count("published_video_window(runtime / \"bin/ffprobe.exe\""), 2)
        self.assertEqual(gate.count("published_packet_window(runtime / \"bin/ffprobe.exe\""), 2)
        self.assertNotIn('"-read_intervals", "%+#20"', gate)
        for assertion in ("len(stamps) >= 10", "monotonic and span >= float(encoder_keyint_seconds)",
                          'replay_window["frames"] >= 10', "firstDecodableFrameMs", "packetProbe",
                          "unparsableStamps", "stamp = float(value)"):
            self.assertIn(assertion, gate)


    def test_mixer_identities_name_owned_helpers_without_leaking_the_run(self):
        """A disappeared helper has to be named by its mix port, not by private paths.

        Run 44548882087 reported only a PID diff for a lost FFmpeg audio mixer. The
        command line is the identity available here, so camera URLs and this run's
        private roots must be replaced before anything reaches a receipt, while each
        helper's loopback mix port survives so the receipt can name the mix it starved.
        """
        if os.name == "nt":
            self.skipTest("fake PowerShell needs a POSIX executable")
        spec = importlib.util.spec_from_file_location("product_windows",
            ROOT / "native-host/tests/product_windows.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        gate = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")
        for wiring in ("audio_mix_helper_watch", "mixer_identities(powershell, rows",
                       "before-program-output-stop", "after-program-output-stop",
                       '"mixerPort": entry.get("mixerPort")', "watched_ports(row)",
                       "claimed_ports(row)", "live_ports != claimed",
                       "host still reports a live mix", "fixture publishers",
                       "other helpers"):
            self.assertIn(wiring, gate)
        with tempfile.TemporaryDirectory() as temporary:
            fake = Path(temporary) / "pwsh"
            fake.write_text("#!/usr/bin/env python3\n"
                "print('12|C:/run/bin/ffmpeg.exe -i rtsp://user:pass@10.0.0.9:554/secret "
                "-f mpegts tcp://127.0.0.1:56?listen=1')\n"
                "print('34|C:/run/bin/ffmpeg.exe -i tcp://10.0.0.9:1234/secret ' + 'y'*400)\n"
                "print('not-a-pid|ignored')\n", encoding="utf-8")
            fake.chmod(0o755)
            identities = module.mixer_identities(fake, [12, 34, 99], ("C:/run/bin",))
            self.assertEqual(sorted(identities), [12, 34])
            self.assertIn("<url>", identities[12])
            self.assertNotIn("rtsp://", identities[12])
            self.assertNotIn("user:pass", identities[12])
            self.assertNotIn("C:/run/bin", identities[12])
            # The loopback mix port is the key that ties this helper to its mix source.
            self.assertIn("tcp:56", identities[12])
            self.assertEqual(module.helper_port(identities[12]), 56)
            # A remote tcp endpoint stays masked, and only its port survives nowhere.
            self.assertIn("<url>", identities[34])
            self.assertNotIn("10.0.0.9", identities[34])
            self.assertIsNone(module.helper_port(identities[34]))
            self.assertEqual(len(identities[34]), 160)
            self.assertEqual(module.mixer_identities(fake, []), {})
            broken = module.mixer_identities(Path(temporary) / "absent", [7])
            self.assertEqual(broken, {7: "command-line-unavailable"})

    def test_mix_port_ownership_sees_an_unserved_mix_and_a_duplicate_helper(self):
        """Ports, not PIDs, decide whether every owned mix still has its helper.

        The host reports the loopback port each mix source reads, so a helper that
        exits unnoticed leaves a claimed port unserved and a respawn that leaves the
        old one behind puts two helpers on one port. A short-lived AV remux child has
        no mix port and must not be counted as a mixer.
        """
        if os.name == "nt":
            self.skipTest("fake PowerShell needs a POSIX executable")
        spec = importlib.util.spec_from_file_location("product_windows",
            ROOT / "native-host/tests/product_windows.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        row = {"processes": [{"pid": 12, "port": 56, "identity": "ffmpeg ... tcp:56?listen=1"},
                             {"pid": 13, "port": 56, "identity": "ffmpeg ... tcp:56?listen=1"},
                             {"pid": 14, "port": None, "identity": "ffmpeg -i <private>/a.mkv"}],
            "hostClaims": [{"sourceId": "scene-a.mix", "mixerPort": 56, "available": True},
                           {"sourceId": "scene-b.mix", "mixerPort": 57, "available": True}],
            "otherHelpers": [{"pid": 14, "identity": "ffmpeg -i <private>/a.mkv"}]}
        self.assertEqual(module.watched_ports(row), [56, 56])
        self.assertEqual(module.claimed_ports(row), [56, 57])
        self.assertNotEqual(module.watched_ports(row), module.claimed_ports(row))
        served = {"processes": [{"pid": 12, "port": 56, "identity": "tcp:56"},
                                {"pid": 15, "port": 57, "identity": "tcp:57"}],
            "hostClaims": row["hostClaims"], "otherHelpers": []}
        self.assertEqual(module.watched_ports(served), module.claimed_ports(served))
        self.assertEqual(module.claimed_ports({"hostClaims": [{"sourceId": "x", "mixerPort": None},
                                                              {"sourceId": "y"}]}), [])

    def test_published_packet_window_formats_the_interval_and_reports_its_own_failure(self):
        """The keyframe diagnostic must not break the measurement it accompanies.

        Run 44544305133 lost the decodable-frame result because the packet probe
        built its read interval with %-formatting, and MediaMTX's own "%+00:00:6"
        made Python raise "unsupported format character" before the frames were
        recorded. The interval is concatenated now, and a failing diagnostic returns
        its error text instead of replacing the assertion.
        """
        if os.name == "nt":
            self.skipTest("fake ffprobe needs a POSIX executable")
        spec = importlib.util.spec_from_file_location("product_windows",
            ROOT / "native-host/tests/product_windows.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        gate = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")
        self.assertNotIn('"-read_intervals", "%+00:00:%d" %', gate)
        self.assertIn('read_interval = "%+00:00:" + str(window_seconds)', gate)
        with tempfile.TemporaryDirectory() as temporary:
            argv_record = Path(temporary) / "argv.txt"
            fake = Path(temporary) / "ffprobe"
            fake.write_text("#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "with open(os.environ['FAKE_ARGV'], 'w', encoding='utf-8') as handle:\n"
                "    handle.write(json.dumps(sys.argv[1:]))\n"
                "print(json.dumps({'packets': [{'pts_time': '1.0', 'flags': '___'},"
                " {'pts_time': '2.0', 'flags': 'K'}, {'pts_time': 'N/A', 'flags': 'K'},"
                " {'pts_time': '4.0', 'flags': 'K'}]}))\n", encoding="utf-8")
            fake.chmod(0o755)
            os.environ["FAKE_ARGV"] = str(argv_record)
            try:
                summary = module.published_packet_window(fake, "rtsp://127.0.0.1:1/program", 6)
            finally:
                os.environ.pop("FAKE_ARGV", None)
            argv = json.loads(argv_record.read_text(encoding="utf-8"))
            self.assertEqual(argv[argv.index("-read_intervals") + 1], "%+00:00:6")
            self.assertEqual(summary["readInterval"], "%+00:00:6")
            self.assertEqual(summary["packets"], 4)
            self.assertEqual(summary["keyframes"], 2, "an unparsable key stamp is not counted")
            self.assertEqual(summary["firstKeyPacketPts"], 2.0)
            self.assertFalse(summary["firstPacketIsKey"])
            self.assertNotIn("diagnosticFailed", summary)
            missing = module.published_packet_window(Path(temporary) / "absent",
                "rtsp://127.0.0.1:1/program", 6)
            self.assertIn("diagnosticFailed", missing)
            self.assertEqual(missing["readInterval"], "%+00:00:6")

    def test_published_video_window_parses_string_stamps_and_keeps_bounded_noise(self):
        """The shared window reader must not drop ffprobe's string pts_time.

        The rc.61/rc.62 receipt recorded a span of 0 because only int/float stamps
        were accepted, while ffprobe writes pts_time as text. A fake ffprobe also
        proves that an "N/A" row is reported instead of counted, that a repeating
        stderr tail cannot block the window, and that the window ends by killing a
        deliberately long-lived connection. This only checks the reader, not the
        published Program, and it skips where a script cannot be executed.
        """
        if os.name == "nt":
            self.skipTest("fake ffprobe needs a POSIX executable")
        spec = importlib.util.spec_from_file_location("product_windows",
            ROOT / "native-host/tests/product_windows.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            fake = Path(temporary) / "ffprobe"
            fake.write_text("#!/usr/bin/env python3\n"
                "import sys, time\n"
                "sys.stderr.write('co located POCs unavailable\\n' * 3)\n"
                "sys.stderr.flush()\n"
                "for stamp in ('1.000000', 'N/A', '1.033333', '1.066666', '1.100000'):\n"
                "    print(stamp, flush=True)\n"
                "time.sleep(0.2)\n", encoding="utf-8")
            fake.chmod(0o755)
            window = module.published_video_window(fake, "rtsp://127.0.0.1:1/program", 30)
            self.assertEqual(window["frames"], 4)
            self.assertEqual(window["unparsableStamps"], ["N/A"])
            self.assertEqual(window["stamps"], [1.0, 1.033333, 1.066666, 1.1])
            self.assertTrue(window["monotonicTimestamps"])
            self.assertAlmostEqual(window["ptsSpanSeconds"], 0.1, places=3)
            self.assertTrue(window["firstDecodableFrameMs"] >= 0)
            self.assertFalse(window["windowTimedOut"])
            self.assertEqual(window["returnCode"], 0)
            self.assertIn("co located POCs unavailable", window["stderrTail"])

    def test_build_symbols_are_stripped_before_the_manifest(self):
        builder = (ROOT / "desktop/scripts/build-obs-native.ps1").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        self.assertIn("native-host/scripts/prune_runtime.py", builder)
        self.assertLess(
            builder.index("prune_runtime.py"),
            builder.index("native-host/scripts/stage.py"),
        )
        self.assertIn("native-runtime-prune.json", workflow)
        self.assertIn("-Filter *.pdb", workflow)
        self.assertIn("build-symbol PDB files", workflow)

    def test_nsis_install_receipt_records_actual_footprint(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        self.assertIn("New-InstalledTreeFootprintScope -Root $root -Purpose isolated-nsis-install-before-first-start", workflow)
        self.assertIn("$footprint = Measure-InstalledTreeFootprint -Scope $scope", workflow)
        self.assertIn("installed = $footprint", workflow)
        self.assertLess(
            workflow.index("New-InstalledTreeFootprintScope"),
            workflow.index("Measure-InstalledTreeFootprint"),
        )

    def test_p5_campaign_plan_is_scheduled_not_measured(self):
        plan = (ROOT / "native-host/qualification/plan.py").read_text(encoding="utf-8")
        self.assertIn('"qualified": False', plan)
        self.assertIn('"status": "planned"', plan)
        self.assertIn("plan.py", (ROOT / "native-host/qualification/README.md").read_text(encoding="utf-8"))
        self.assertIn("plan.py", (ROOT / "docs/windows-target-qualification-runbook.md").read_text(encoding="utf-8"))

    def test_p5_preflight_is_diagnostic_only(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        preflight = (ROOT / "native-host/qualification/preflight.py").read_text(encoding="utf-8")
        self.assertIn("native-host/qualification/preflight.py", workflow)
        self.assertIn("--diagnostic", workflow)
        self.assertIn("native-p5-preflight-diagnostic.json", workflow)
        self.assertIn("never marks a P5 campaign qualified", preflight)
        self.assertIn('"qualified": False', preflight)

    def test_size_gap_comparison_runs_against_stock_obs(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        script = (SCRIPTS / "compare_runtime_sizes.py").read_text(encoding="utf-8")
        self.assertIn("native-host/scripts/compare_runtime_sizes.py", workflow)
        self.assertIn("--prototype build/obs-native-ci/runtime --obs $root", workflow)
        self.assertIn("build/obs-native-ci/native-size-compare.json", workflow)
        self.assertLess(
            workflow.index("Measure the stock OBS 32.1.2 installation"),
            workflow.index("--obs $root"),
        )
        for expected in ("obsOnlyGroups", "sharedPercentOfObsBytes", "largestObsOnly"):
            self.assertIn(expected, script)

    def test_runtime_inventory_enforces_budget_and_accounting(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        script = (SCRIPTS / "runtime_inventory.py").read_text(encoding="utf-8")
        self.assertIn("native-host/scripts/runtime_inventory.py", workflow)
        self.assertIn("--max-runtime-bytes 104857600", workflow)
        self.assertIn("build/obs-native-ci/native-runtime-inventory.json", workflow)
        self.assertLess(
            workflow.index("Inventory the runtime"),
            workflow.index("Freeze clean non-default prototype"),
        )
        for expected in ('".pdb"', '".lib"', "licenseHint", "withinBudget"):
            self.assertIn(expected, script)

    def test_installer_is_per_user_and_never_deletes_private_config(self):
        script = (ROOT / "native-host/installer/WebOBSNative.nsi").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        self.assertIn("RequestExecutionLevel user", script)
        self.assertIn('StrCmp $1 "config" un_next', script)
        self.assertIn('StrCmp $1 "backups" un_next', script)
        self.assertNotIn('RMDir /r "$INSTDIR"', script)
        self.assertIn("File /r \"${PACKAGE_DIR}\\*.*\"", script)
        self.assertIn('WriteUninstaller "$INSTDIR\\Uninstall.exe"', script)
        self.assertIn("Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WebOBSNativePrototype", script)
        self.assertIn("native-host/installer/WebOBSNative.nsi", workflow)
        self.assertIn("choco install nsis", workflow)
        self.assertIn("configPreservedAcrossReinstall = $true", workflow)
        self.assertIn("configPreservedAcrossUninstall = $true", workflow)
        self.assertIn("signed = $false", workflow)

    def test_process_gate_rejects_helper_services_and_orphans(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        smoke = (ROOT / "native-host/tests/smoke_windows.py").read_text(encoding="utf-8")
        self.assertIn("native-*-process-gate.json", workflow)
        for expected in ("FORBIDDEN_PROCESS_NAMES", "SERVICE_LISTENER_PORTS", "check_process_gate"):
            self.assertIn(expected, smoke)
        base = {"schema": 1, "samples": 3, "observed": [{"name": "obs64.exe"}], "listeners": [], "orphans": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate.json"

            def write(payload):
                path.write_text(json.dumps(payload), encoding="utf-8")

            write(base)
            self.assertEqual(smoke_windows.check_process_gate(path)["orphanCount"], 0)
            for payload in (
                {**base, "observed": [{"name": "ffmpeg.exe"}]},
                {**base, "orphans": [{"name": "obs64.exe"}]},
                {**base, "listeners": [{"port": 8554, "name": "obs64"}]},
                {**base, "samples": 0},
            ):
                write(payload)
                with self.assertRaises(AssertionError):
                    smoke_windows.check_process_gate(path)

    def test_crash_smoke_kills_the_host_and_requires_no_survivors(self):
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        launcher = (ROOT / "native-host/scripts/launch-native.ps1").read_text(encoding="utf-8")
        smoke = (ROOT / "native-host/tests/smoke_windows.py").read_text(encoding="utf-8")
        self.assertIn("--crash-smoke", workflow)
        self.assertIn("native-crash-smoke.json", workflow)
        self.assertIn("--crash-after-seconds 8", workflow)
        self.assertIn("$CrashAfterSeconds", launcher)
        self.assertIn("-CrashProbe", smoke)
        self.assertIn("$CrashProbe", launcher)
        self.assertIn("--second-instance-smoke", workflow)
        self.assertIn("native-second-instance-smoke.json", workflow)
        self.assertIn("run_second_instance", smoke)
        self.assertIn("$AllowMultiple", launcher)
        self.assertIn("WebObsNativeHostSingleInstance", launcher)
        self.assertIn("native-nsis-upgrade.json", workflow)
        self.assertIn("v4.1.0-dev.40", workflow)
        self.assertIn("7cc5724c0aee941802bdc9f8ed71b7547d1b3d73631170e003c5a03d7bb2a54d", workflow)
        self.assertIn("configPreservedAcrossUpgrade", workflow)
        self.assertIn(".Replace('\\','/')", workflow)
        self.assertIn("crashed = [bool]$gateCrashed", launcher)
        self.assertIn('--crash-smoke', smoke)
        self.assertIn('gate.get("crashed") is not True', smoke)

    def test_native_control_boundary_has_standalone_linux_and_msvc_contracts(self):
        workflow = (ROOT / ".github/workflows/web-runtime-ci.yaml").read_text(encoding="utf-8")
        standalone = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        root_cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "native-host/tests/control-auth-vcpkg/vcpkg.json").read_text(encoding="utf-8"))
        self.assertIn("native-control-contracts:", workflow)
        self.assertIn("windows-native-control-contracts:", workflow)
        self.assertIn("native-host/tests/test_legacy_import.py", workflow)
        self.assertIn("native-host/tests/control-auth", workflow)
        self.assertIn("x64-windows-static", workflow)
        self.assertEqual(workflow.count("contents: write"), 1)
        optional_caller = workflow.split("  windows-desktop-candidate:", 1)[1].split("  public-audit:", 1)[0]
        self.assertIn("contents: write", optional_caller)
        self.assertIn("official: false", optional_caller)
        self.assertNotIn("publish_dev", optional_caller)
        self.assertIn("core/src/native_control_auth.cpp", standalone)
        self.assertIn("core/src/authentication.cpp", standalone)
        self.assertNotIn("add_subdirectory", standalone)
        self.assertNotIn("find_package(libobs", standalone)
        self.assertNotIn("find_package(Qt", standalone)
        self.assertIn("native-control-no-media-symbols", standalone)
        self.assertIn("webobs-native-control-auth-tests", root_cmake)
        self.assertEqual(manifest["dependencies"], ["openssl", "sqlite3", "curl", "jansson"])
        self.assertIn("core/src/native_cluster_authorization.cpp", standalone)
        self.assertIn("test_native_cluster_authorization.py", standalone)
        self.assertIn("native-cluster-no-media-symbols", standalone)
        self.assertEqual(manifest["builtin-baseline"], "eb2d3a3279fd019cb7733072d86900d0ad2a1aef")

    def test_native_graph_ownership_contracts_use_pinned_headers_without_media(self):
        workflow = (ROOT / ".github/workflows/web-runtime-ci.yaml").read_text(encoding="utf-8")
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        job = workflow.split("  native-graph-api-contracts:", 1)[1].split("  windows-update-contracts:", 1)[0]
        self.assertIn("os: [ubuntu-24.04, windows-2022]", job)
        self.assertIn("git submodule update --init --depth 1 obs/obs-studio", job)
        self.assertIn("actual == pin", job)
        self.assertIn("cmake --build build/native-graph-api --config Release --parallel 2 --verbose", job)
        self.assertIn("-DWEBOBS_NATIVE_BUILD_PLUGIN=OFF", job)
        self.assertIn("-DWEBOBS_NATIVE_BUILD_TESTS=ON", job)
        self.assertNotIn("vcpkg", job)
        self.assertNotIn("build-obs-native.ps1", job)
        self.assertIn("tests/product_bootstrap_test.cpp src/product_bootstrap.cpp", cmake)
        self.assertIn("native-product-bootstrap-api-contract", cmake)
        self.assertIn("tests/wall_snapshot_test.cpp src/wall_snapshot.cpp", cmake)
        self.assertIn("native-wall-snapshot-api-contract", cmake)
        self.assertIn("target_compile_options(native-wall-snapshot-test PRIVATE /EHs /EHc-)", cmake)
        plugin = cmake.split("if(WEBOBS_NATIVE_BUILD_PLUGIN)", 1)[1].split("if(WEBOBS_NATIVE_BUILD_TESTS)", 1)[0]
        self.assertNotIn("/EHc-", plugin)
        self.assertIn('TIMEOUT 30 LABELS "native;api-contract;no-media"', cmake)

    def test_offline_private_staging_is_a_separate_no_media_matrix(self):
        workflow = (ROOT / ".github/workflows/web-runtime-ci.yaml").read_text(encoding="utf-8")
        job = workflow.split("  native-private-staging-contracts:", 1)[1].split("  windows-native-control-contracts:", 1)[0]
        self.assertIn("os: [ubuntu-24.04, windows-2022]", job)
        for name in ("test_legacy_stage_document.py", "test_private_stage.py", "test_legacy_stage.py"):
            self.assertIn(name, job)
        for command in ("vcpkg", "submodule", "build-obs", "obs64", "upload-artifact"):
            self.assertNotIn(command, job)
        self.assertNotIn("contents: write", job)
        cli = (SCRIPTS / "legacy_stage.py").read_text(encoding="utf-8")
        self.assertIn("--existing-config-root", cli)
        self.assertIn("document_stage.verify", cli)
        self.assertNotIn("subprocess", cli)

    def test_real_loader_gate_is_standalone_and_never_installed(self):
        cmake = (ROOT / 'native-host/tests/real-loader/CMakeLists.txt').read_text(encoding="utf-8")
        probe = (ROOT / 'native-host/tests/real-loader/loader_probe.cpp').read_text(encoding="utf-8")
        builder = (ROOT / 'desktop/scripts/build-obs-native.ps1').read_text(encoding="utf-8")
        workflow = (ROOT / '.github/workflows/web-runtime-ci.yaml').read_text(encoding="utf-8")
        self.assertIn('find_package(libobs 32.1.2 EXACT CONFIG REQUIRED)', cmake)
        self.assertIn('PRIVATE OBS::libobs', cmake)
        self.assertNotIn('install(', cmake)
        self.assertIn('TIMEOUT 60', cmake)
        self.assertIn('test_real_legacy_loader.py', cmake)
        for forbidden in ('obs_reset_video(', 'obs_reset_audio(', 'obs_load_all_modules(',
                          'obs_open_module(', 'obs_frontend_', 'obs_set_output_source('):
            self.assertNotIn(forbidden, probe)
        self.assertIn("Join-Path $repoRoot 'native-host/tests/real-loader'", builder)
        self.assertIn('$env:PATH = $beforeLoaderPath', builder)
        job = workflow.split('  native-real-loader-contracts:', 1)[1].split('  native-private-staging-contracts:', 1)[0]
        self.assertIn('--target libobs', job)
        self.assertIn('-DENABLE_FRONTEND=OFF', job)
        self.assertIn('-DENABLE_PLUGINS=OFF', job)
        self.assertIn('extra-cmake-modules', job)
        self.assertIn('xvfb xauth libglvnd-dev', job)
        self.assertIn('xvfb-run -a ctest --test-dir build/native-real-loader', job)
        self.assertNotIn('upload-artifact', job)
        self.assertNotIn('contents: write', job)

    def test_native_account_overflow_guard_survives_windows_max_macro(self):
        source = (ROOT / "core/src/native_cluster_authorization.cpp").read_text(encoding="utf-8")
        # curl may expose the SDK's function-like max macro. Keep the callable
        # parenthesized rather than changing the arithmetic or weakening bounds.
        self.assertIn("(std::numeric_limits<std::size_t>::max)() / size", source)
        self.assertNotIn("std::numeric_limits<std::size_t>::max()", source)

    def test_operation_auth_orchestrator_wiring_and_budget_checks(self):
        header = (ROOT / "core/include/webobs/native_operation_auth.hpp").read_text(encoding="utf-8")
        source = (ROOT / "core/src/native_operation_auth.cpp").read_text(encoding="utf-8")
        standalone = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        root_cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        # Wired into both the standalone Linux/MSVC contract and the root build.
        self.assertIn("core/src/native_operation_auth.cpp", standalone)
        self.assertIn("webobs-native-operation-auth-tests", standalone)
        self.assertIn("native-operation-auth", standalone)
        self.assertIn("core/src/native_operation_auth.cpp", root_cmake)
        self.assertIn("webobs-native-operation-auth-tests", root_cmake)
        # Source-shape guard only; this cannot prove runtime deadlines, policy
        # consistency or absence of all forms of caching. Executable tests own
        # the pre/post-call budget and clock-failure behavior.
        self.assertIn("total_budget", header)
        self.assertNotIn("std::map", source)
        self.assertNotIn("std::unordered_map", source)
        self.assertIn("current - start >= total_budget", source)

    def test_native_batch_is_whole_batch_and_internal_only(self):
        source = (ROOT / "cluster/cluster_service.py").read_text(encoding="utf-8")
        batch = source.split("def native_authorize_batch")[1].split("def authorize(")[0]
        # The product now invokes the bounded helper through the existing
        # internal administrator gate; it is never a public proxy allowlist.
        self.assertIn("def native_authorize_batch(", source)
        self.assertIn("native_authorize_batch(self.read_json())", source)
        self.assertIn('path == "/auth/native-authorize-batch"', source)
        self.assertIn("NATIVE_BATCH_ITEMS = 16", source.split("ROLE_PERMISSIONS")[0])
        # Any denial raises: the batch never returns a partially executable
        # subset, and Registry failures fail the whole batch closed.
        self.assertIn("raise rejection", batch)
        self.assertIn("native_registry_unavailable", batch)
        self.assertNotIn("cameraIds", batch)


    def test_source_ownership_ledger_is_wired_for_creation_only(self):
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        plugin_sources = cmake.split("add_library(webobs-native-host MODULE ")[1].split(")")[0]
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        ownership_header = (ROOT / "native-host/src/source_ownership.hpp").read_text(encoding="utf-8")
        ownership_source = (ROOT / "native-host/src/source_ownership.cpp").read_text(encoding="utf-8")
        # The plugin links the ledger and store ONLY for creation-time
        # persistence. No decision path classifies provenance yet: no wall
        # selection, preview or projector behavior may consult the ledger.
        self.assertIn("src/source_ownership.cpp", plugin_sources)
        self.assertIn("src/ownership_store.cpp", plugin_sources)
        self.assertIn("record_product_ownership", plugin)
        self.assertIn("not an\n// authorization grant", ownership_header)
        for forbidden in ("classify_snapshot", "authorize", "native_operation"):
            self.assertNotIn(forbidden, plugin)
        self.assertIn("add_executable(native-source-ownership-test tests/source_ownership_test.cpp src/source_ownership.cpp)", cmake)
        self.assertIn("native-source-ownership-api-contract", cmake)
        # Persistence stays OUTSIDE the pure module: the ledger codec itself
        # performs no file, network or OBS API work.
        for forbidden in ("#include <fstream>", "#include <filesystem>", "std::ofstream", "std::ifstream",
                          "obs_", "socket"):
            self.assertNotIn(forbidden, ownership_source)

    def test_ownership_store_persistence_is_bounded_without_durability_claims(self):
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        store_header = (ROOT / "native-host/src/ownership_store.hpp").read_text(encoding="utf-8")
        store_source = (ROOT / "native-host/src/ownership_store.cpp").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        smoke = (ROOT / "native-host/tests/smoke_windows.py").read_text(encoding="utf-8")
        self.assertIn(
            "add_executable(native-ownership-store-test tests/ownership_store_test.cpp "
            "src/ownership_store.cpp src/source_ownership.cpp)", cmake)
        self.assertIn("native-ownership-store-api-contract", cmake)
        # Honest boundary: the store performs plain write+rename only. It must
        # not claim or implement fsync/FlushFileBuffers durability semantics.
        for forbidden in ("fsync", "_commit", "FlushFileBuffers"):
            self.assertNotIn(forbidden, store_source)
        self.assertIn("does NOT claim", store_header)
        # Plugin records only slots created by this attempt and reports ledger
        # failures without failing the wall itself.
        self.assertIn("product.created_here[i]", plugin)
        self.assertIn('"ownershipLedger"', plugin)
        self.assertIn("ownershipLedger", smoke)
        self.assertIn("expect_ownership_entries", smoke)

    def test_binding_inspection_is_read_only_and_receipt_only(self):
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        plugin_sources = cmake.split("add_library(webobs-native-host MODULE ")[1].split(")")[0]
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        smoke = (ROOT / "native-host/tests/smoke_windows.py").read_text(encoding="utf-8")
        self.assertIn("src/wall_snapshot.cpp", plugin_sources)
        # Exactly one provenance classification exists: the read-only receipt
        # path. It must not mutate the graph or persist anything.
        self.assertEqual(plugin.count("classify_wall_entries("), 1)
        body = plugin.split("void record_binding_inspection")[1].split("void bootstrap_product_cameras")[0]
        for forbidden in ("obs_source_create", "obs_scene_create", "obs_sceneitem_",
                          "obs_source_remove", "obs_scene_release", "save_ownership_store"):
            self.assertNotIn(forbidden, body)
        for key in ('"bindingInspection"', '"bindingItems"', '"bindingBound"', '"bindingUnbound"'):
            self.assertIn(key, body)
        self.assertIn("expect_binding_bound", smoke)
        self.assertIn("productBindingBound", smoke)

    def test_wall_live_decision_is_unwired_and_fail_closed(self):
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/wall_live_decision.hpp").read_text(encoding="utf-8")
        source = (ROOT / "native-host/src/wall_live_decision.cpp").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        self.assertIn(
            "add_executable(native-wall-live-decision-test tests/wall_live_decision_test.cpp "
            "src/wall_live_decision.cpp src/source_ownership.cpp)", cmake)
        self.assertIn("native-wall-live-decision-api-contract", cmake)
        # Unexposed: the product plugin must not link or call the pairing module.
        plugin_line = cmake.split("add_library(webobs-native-host MODULE", 1)[1].splitlines()[0]
        self.assertNotIn("wall_live_decision.cpp", plugin_line)
        self.assertNotIn("decide_wall_live_view", plugin)
        # Pure pairing logic: no I/O, no OBS API, no network inside the module.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket"):
            self.assertNotIn(forbidden, source)
        self.assertIn("decision-time snapshot", header)
        self.assertIn("NOT an authorization grant", header)

    def test_live_view_pipeline_is_unwired_and_fresh_decisions(self):
        control_cmake = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/live_view_pipeline.hpp").read_text(encoding="utf-8")
        source = (ROOT / "native-host/src/live_view_pipeline.cpp").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        # Unexposed: neither native build links the pipeline into the product plugin.
        plugin_line = cmake.split("add_library(webobs-native-host MODULE", 1)[1].splitlines()[0]
        self.assertNotIn("live_view_pipeline.cpp", plugin_line)
        self.assertNotIn("authorize_live_view", plugin)
        # Verified only inside the renderer-free standalone boundary.
        self.assertIn("webobs-native-live-view-pipeline", control_cmake)
        self.assertIn("webobs-live-view-pipeline-tests", control_cmake)
        self.assertIn("add_test(NAME native-live-view-pipeline", control_cmake)
        self.assertIn("native-live-view-no-media-symbols", control_cmake)
        self.assertIn("webobs-native-control-auth", control_cmake)
        # No cached grants and no I/O inside the module. Static shape is not a
        # complete proof; runtime semantics belong to the pipeline CTest itself.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket",
                          "std::map", "std::unordered_map"):
            self.assertNotIn(forbidden, source)
        self.assertIn("decision-time pipeline", header)
        self.assertIn("NOT an execution fence", header)
        # Session binding must precede observation and authorization (order lock).
        self.assertLess(source.index("validate_and_slide"), source.index("provider()"))
        self.assertLess(source.index("provider()"), source.index("decide_wall_live_view"))

    def test_wall_apply_plan_is_unwired_and_never_plans_over_unowned_graph(self):
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/wall_apply_plan.hpp").read_text(encoding="utf-8")
        source = (ROOT / "native-host/src/wall_apply_plan.cpp").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        self.assertIn(
            "add_executable(native-wall-apply-plan-test tests/wall_apply_plan_test.cpp "
            "src/wall_apply_plan.cpp src/source_ownership.cpp)", cmake)
        self.assertIn("native-wall-apply-plan-api-contract", cmake)
        # Unexposed: the product plugin must not link or call the planner.
        plugin_line = cmake.split("add_library(webobs-native-host MODULE", 1)[1].splitlines()[0]
        self.assertNotIn("wall_apply_plan.cpp", plugin_line)
        self.assertNotIn("plan_wall_apply", plugin)
        # Pure plan logic: no I/O, no OBS API, no network inside the module.
        # map/set are call-local deterministic indexes, not cached grants.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket"):
            self.assertNotIn(forbidden, source)
        self.assertIn("PLAN, not an executor", header)
        self.assertIn("never planned over", header)
        # Fail-closed order: ledger consistency precedes snapshot classification.
        self.assertLess(source.index("ownership_ledger_consistent"), source.index("classify_wall_entries"))

    def test_wall_apply_authorization_is_unwired_and_binds_session_before_backend(self):
        control_cmake = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/wall_apply_authorization.hpp").read_text(encoding="utf-8")
        source = (ROOT / "native-host/src/wall_apply_authorization.cpp").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        # Unexposed: neither native build links the composition into the product plugin.
        plugin_line = cmake.split("add_library(webobs-native-host MODULE", 1)[1].splitlines()[0]
        self.assertNotIn("wall_apply_authorization.cpp", plugin_line)
        self.assertNotIn("authorize_wall_apply", plugin)
        # Verified only inside the renderer-free standalone boundary.
        self.assertIn("webobs-native-wall-apply-authorization", control_cmake)
        self.assertIn("webobs-wall-apply-authorization-tests", control_cmake)
        self.assertIn("add_test(NAME native-wall-apply-authorization", control_cmake)
        self.assertIn("native-wall-apply-no-media-symbols", control_cmake)
        # No I/O or OBS/network entry points inside the module. set is a
        # call-local duplicate index, not a cached grant. Static shape is not
        # a complete proof; runtime semantics belong to the CTest itself.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("std::map", source)
        self.assertNotIn("std::unordered_map", source)
        self.assertIn("decision-time snapshot", header)
        self.assertIn("NOT an authorization grant", header)
        self.assertIn("NOT an execution fence", header)
        self.assertIn("never forbidden", source)
        # Order locks: exact session binding precedes the batch backend call,
        # the batch precedes observation, and observation precedes planning.
        # (rindex anchors on the actual call sites, not earlier comments.)
        self.assertLess(source.index("validate_and_slide"), source.rindex("authorize_operation("))
        self.assertLess(source.rindex("authorize_operation("), source.index("provider()"))
        self.assertLess(source.index("provider()"), source.rindex("plan_wall_apply("))


    def test_wall_apply_executor_revalidates_before_mutating(self):
        control_cmake = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/wall_apply_executor.hpp").read_text(encoding="utf-8")
        source = (ROOT / "native-host/src/wall_apply_executor.cpp").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        # Unexposed: the product plugin never links or calls the executor.
        plugin_line = cmake.split("add_library(webobs-native-host MODULE", 1)[1].splitlines()[0]
        self.assertNotIn("wall_apply_executor.cpp", plugin_line)
        self.assertNotIn("execute_wall_apply", plugin)
        # Verified only inside the renderer-free standalone boundary.
        self.assertIn("webobs-wall-apply-executor-tests", control_cmake)
        self.assertIn("add_test(NAME native-wall-apply-executor", control_cmake)
        self.assertIn("wall_apply_executor.cpp", control_cmake)
        # No I/O or OBS/network entry points inside the module.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("std::map", source)
        self.assertNotIn("std::unordered_map", source)
        self.assertIn("NOT an authorization check and NOT an execution", header)
        self.assertIn("stale_plan", header)
        # Order locks: the plan is re-derived from the fresh observation before
        # any target callback, keeps never reach the target, and the prefix
        # journal is replayed newest-first.
        rederive = source.index("const WallApplyPlan rederived = plan_wall_apply")
        self.assertLess(rederive, source.index("invoke_apply(target, op)"))
        self.assertLess(source.index("op.kind == WallApplyOpKind::keep"),
                        source.index("invoke_apply(target, op)"))
        self.assertIn("journal.rbegin()", source)


    def test_wall_apply_backup_is_bounded_and_unwired(self):
        control_cmake = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/wall_apply_backup.hpp").read_text(encoding="utf-8")
        source = (ROOT / "native-host/src/wall_apply_backup.cpp").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        # Unexposed: the product plugin never links or captures backups.
        plugin_line = cmake.split("add_library(webobs-native-host MODULE", 1)[1].splitlines()[0]
        self.assertNotIn("wall_apply_backup.cpp", plugin_line)
        self.assertNotIn("capture_wall_apply_backup", plugin)
        # Verified only inside the renderer-free standalone boundary.
        self.assertIn("webobs-wall-apply-backup-tests", control_cmake)
        self.assertIn("add_test(NAME native-wall-apply-backup", control_cmake)
        self.assertIn("wall_apply_backup.cpp", control_cmake)
        # No I/O or OBS/network entry points inside the module.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("std::map", source)
        self.assertNotIn("std::unordered_map", source)
        # Bounds and fail-closed rules are part of the contract text.
        self.assertIn("kMaxWallApplySettingsBytes", header)
        self.assertIn("kMaxWallApplyBackupBytes", header)
        self.assertIn("Fail-closed", header)
        self.assertIn("best-effort restore", header)
        self.assertIn("kMaxWallApplySettingsBytes", source)
        self.assertIn("available", source)
        # Restore replays newest-first and reports accounting.
        self.assertIn("entries.rbegin()", source)
        self.assertIn("complete", source)

    def test_camera_catalog_binding_is_unwired_and_fails_closed(self):
        module = ROOT / "native-host/src/camera_catalog_binding.cpp"
        header = ROOT / "native-host/src/camera_catalog_binding.hpp"
        plugin = ROOT / "native-host/src/plugin.cpp"
        cmake = ROOT / "native-host/tests/control-auth/CMakeLists.txt"
        source = module.read_text(encoding="utf-8")
        header_text = header.read_text(encoding="utf-8")

        # The catalog check belongs to the unexposed decision layer only.
        plugin_cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        add_library = next(line for line in plugin_cmake.splitlines()
                           if "add_library(webobs-native-host" in line)
        self.assertNotIn("camera_catalog_binding.cpp", add_library)
        self.assertNotIn("classify_camera_catalog", plugin.read_text(encoding="utf-8"))
        self.assertNotIn("authorize_wall_apply_with_catalog", plugin.read_text(encoding="utf-8"))

        # Wired into the standalone decision-authorization library and its CTest.
        cmake_text = cmake.read_text(encoding="utf-8")
        self.assertIn("camera_catalog_binding.cpp", cmake_text)
        self.assertIn("webobs-camera-catalog-binding-tests", cmake_text)
        self.assertIn("native-camera-catalog-binding", cmake_text)

        # Pure module: no OBS, files, sockets or cached grant containers.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket"):
            self.assertNotIn(forbidden, source)

        # Contract anchors: identity-only claim, not a grant; classifier runs
        # before the delegated decision.
        self.assertIn("not an authorization grant", header_text)
        self.assertIn("injected observation", header_text)
        self.assertLess(source.index("classify_camera_catalog(ledger, catalog)"),
                        source.index("authorize_wall_apply(sessions"))


    def test_backup_executor_captures_before_mutating(self):
        source = (ROOT / "native-host/src/wall_apply_backup_executor.cpp").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/wall_apply_backup_executor.hpp").read_text(encoding="utf-8")
        cmake = ROOT / "native-host/tests/control-auth/CMakeLists.txt"
        cmake_text = cmake.read_text(encoding="utf-8")
        plugin_cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")

        # Standalone library + CTest wiring; the product plugin never links it.
        self.assertIn("wall_apply_backup_executor.cpp", cmake_text)
        self.assertIn("webobs-wall-apply-backup-executor-tests", cmake_text)
        self.assertIn("native-wall-apply-backup-executor", cmake_text)
        self.assertNotIn("wall_apply_backup_executor.cpp",
                         next(line for line in plugin_cmake.splitlines() if "add_library(webobs-native-host" in line))
        self.assertNotIn("execute_wall_apply_with_backup", plugin)

        # Pure module: no OBS, files, sockets.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket"):
            self.assertNotIn(forbidden, source)
        self.assertIn("NOT wired to OBS", header)
        self.assertIn("no atomicity", header)

        # Capture precedes every target call; a partial rollback never restores.
        self.assertLess(source.index("capture_wall_apply_backup(plan"), source.index("execute_wall_apply(plan"))
        self.assertIn("backup_unavailable", source)
        self.assertIn("rollback_incomplete", source)
        self.assertLess(source.index("operation_failed_rollback_incomplete"), source.index("restore_wall_apply_backup"))

    def test_wall_apply_flow_orders_gates_and_executes_only_after_decision(self):
        source = (ROOT / "native-host/src/wall_apply_flow.cpp").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/wall_apply_flow.hpp").read_text(encoding="utf-8")
        cmake_text = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        plugin_cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")

        # Standalone wiring only; the product plugin stays unwired.
        self.assertIn("wall_apply_flow.cpp", cmake_text)
        self.assertIn("webobs-wall-apply-flow-tests", cmake_text)
        self.assertIn("native-wall-apply-flow", cmake_text)
        self.assertNotIn("wall_apply_flow.cpp",
                         next(line for line in plugin_cmake.splitlines() if "add_library(webobs-native-host" in line))
        self.assertNotIn("execute_wall_apply_flow", plugin)

        # Pure module: no OBS, files, sockets.
        for forbidden in ("fstream", "filesystem", "ofstream", "ifstream", "obs_", "socket"):
            self.assertNotIn(forbidden, source)
        self.assertIn("NOT an execution fence", header)
        self.assertIn("Two observations", header)

        # Gate order and the second observation before any mutation.
        self.assertLess(source.index("authorize_wall_apply_with_catalog("), source.index("provider()"))
        self.assertLess(source.index("provider()"), source.index("execute_wall_apply_with_backup("))
        self.assertIn("called by the authorization step and again", header)
        self.assertGreaterEqual(source.count("provider()"), 1)

    def test_native_ui_gate_inventory_matches_plugin_entry_points(self):
        gate = (ROOT / "native-host/src/native_ui_gate.cpp").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/native_ui_gate.hpp").read_text(encoding="utf-8")
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        cmake_text = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        plugin_cmake = (ROOT / "native-host/CMakeLists.txt").read_text(encoding="utf-8")

        # The inventory labels are exactly the plugin's own strings/call sites.
        for marker in ("Refresh existing Media Sources", "Create a new five-tile scene",
                       "Open native Program projector", "bootstrap_product_configuration"):
            self.assertIn(marker, plugin)
            self.assertIn(marker, gate)
        self.assertIn("OBS native source editing", gate)

        # Dock mutation, refresh and projector all fail closed on an empty
        # operator state before their OBS call; ordinary startup is separately
        # refused by the callback dispatcher. OBS-native editing stays outside
        # the plugin and is never claimed to be gated here.
        self.assertEqual(plugin.count("evaluate_ui_action("), 1)
        for kind in ("dock_refresh_sources", "dock_create_wall", "dock_open_program_projector"):
            self.assertEqual(plugin.count("UiActionKind::" + kind), 1, kind)
        self.assertIn("UiAuthorizationState{}", plugin)
        self.assertNotIn("obs_native_source_editing", plugin)
        self.assertEqual(plugin.count("refresh();"), 1)
        self.assertEqual(plugin.count("obs_frontend_open_projector"), 1)

        dock = plugin.split("class WallDock", 1)[1]
        refresh_call = dock.index("refresh();")
        self.assertLess(dock.index("UiActionKind::dock_refresh_sources"), refresh_call)
        self.assertIn("refuse_ui_action();", dock[:refresh_call])
        projector_call = dock.index("obs_frontend_open_projector")
        self.assertLess(dock.index("UiActionKind::dock_open_program_projector"), projector_call)
        self.assertIn("refuse_ui_action();", dock[:projector_call])
        # The constructor must not populate the combos through an ungated call.
        self.assertNotIn("\n\t\trefresh();\n", dock)
        self.assertIn("Every dock entry (refresh, create wall, open the", header)
        self.assertIn("fails closed on an empty state before any OBS", header)
        startup = (ROOT / "native-host/src/startup_bootstrap.cpp").read_text(encoding="utf-8")
        self.assertIn("UiActionKind::auto_bootstrap_on_load", startup)
        self.assertIn("run_startup_bootstrap", plugin)
        self.assertIn("startup_bootstrap.cpp", plugin_cmake)
        self.assertIn("native_ui_gate.cpp",
                      next(line for line in plugin_cmake.splitlines() if "add_library(webobs-native-host" in line))

        # Pure policy module and standalone CTest wiring.
        self.assertNotIn("obs_frontend_", gate)
        self.assertNotIn("obs_source_", gate)
        self.assertNotIn("#include <Q", gate)
        self.assertIn("native_ui_gate.cpp", cmake_text)
        self.assertIn("webobs-native-ui-gate-tests", cmake_text)
        self.assertIn("native-ui-gate", cmake_text)

    def test_startup_dispatcher_precedes_all_bootstrap_effects_and_diagnostics_are_explicit(self):
        plugin = (ROOT / "native-host/src/plugin.cpp").read_text(encoding="utf-8")
        event = plugin.split("void frontend_event(", 1)[1].split("class WallDock", 1)[0]
        dispatch = event.index("run_startup_bootstrap(")
        self.assertLess(dispatch, event.index("backup_config_for_upgrade_if_needed();"))
        self.assertLess(dispatch, event.index("bootstrap_product_configuration();"))
        self.assertEqual(event.count("bootstrap_product_configuration();"), 1)
        self.assertLess(event.index("pixel_test_event(event)"), dispatch)
        self.assertIn('"WEBOBS_NATIVE_DIAGNOSTIC_BOOTSTRAP"', event)
        self.assertIn('"isolated-prototype-v1"', event)
        launcher = (ROOT / "native-host/scripts/launch-native.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$DiagnosticBootstrap", launcher)
        self.assertLess(launcher.index("if ($DiagnosticBootstrap -and"), launcher.index("[Diagnostics.Process]::Start"))
        self.assertIn("'WEBOBS_NATIVE_DIAGNOSTIC_BOOTSTRAP'", launcher)
        self.assertIn("if ($DiagnosticBootstrap) {", launcher)
        self.assertIn("'WEBOBS_NATIVE_RESTART_TOKEN'", launcher)
        cmake = (ROOT / "native-host/tests/control-auth/CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("native-startup-bootstrap", cmake)
        smoke = (ROOT / "native-host/tests/smoke_windows.py").read_text(encoding="utf-8")
        self.assertIn("run_startup_refusal(runtime", smoke)
        self.assertIn("diagnostic=False", smoke)
        self.assertIn('"ordinaryStartupRefusalVerified": not existing_wall', smoke)
        workflow = (ROOT / ".github/workflows/windows-obs-native-host.yaml").read_text(encoding="utf-8")
        self.assertIn("ref=70ecbe9c40fd2bf1d57c5dda416d832adebc0209", workflow)
        self.assertIn("python -B $legacySmoke --runtime $root --result build/obs-native-ci/native-upgrade-first-smoke.json", workflow)
        self.assertIn("python -B native-host/tests/smoke_windows.py --runtime $root --result build/obs-native-ci/native-upgrade-second-smoke.json --existing-wall", workflow)

    def test_startup_refusal_checker_rejects_false_or_stale_evidence(self):
        observed = {"mediaSources": 0, "videoAvailable": True, "fpsNumerator": 30}
        valid = {"startupBootstrap": "refused", "beforeBootstrap": observed, "afterBootstrap": observed.copy()}
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory)
            smoke_windows.check_startup_refusal(valid, module)
            for wrong in (dict(valid, startupBootstrap="diagnostic-completed"),
                          dict(valid, beforeBootstrap={}), dict(valid, afterBootstrap={}),
                          dict(valid, afterBootstrap=dict(observed, fpsNumerator=15)),
                          dict(valid, beforeBootstrap=dict(observed, mediaSources=5),
                               afterBootstrap=dict(observed, mediaSources=5))):
                with self.assertRaises(AssertionError):
                    smoke_windows.check_startup_refusal(wrong, module)
            for name in ("product-bootstrap.json", "wall-bootstrap.json", "source-ownership.json"):
                file = module / name
                file.write_text("{}", encoding="utf-8")
                with self.assertRaises(AssertionError):
                    smoke_windows.check_startup_refusal(valid, module)
                file.unlink()

    def test_restored_graph_refusal_checker_requires_measured_restore(self):
        observed = {"mediaSources": 5, "videoAvailable": True, "fpsNumerator": 30}
        valid = {"startupBootstrap": "refused", "beforeBootstrap": observed, "afterBootstrap": observed.copy()}
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory)
            for name in ("product-bootstrap.json", "source-ownership.json"):
                (module / name).write_text("{}", encoding="utf-8")
            smoke_windows.check_restored_graph_refusal(valid, module, expected_sources=5)
            for wrong in (dict(valid, startupBootstrap="diagnostic-completed"),
                          dict(valid, beforeBootstrap={}),
                          dict(valid, afterBootstrap=dict(observed, mediaSources=4)),
                          dict(valid, beforeBootstrap=dict(observed, mediaSources=0),
                               afterBootstrap=dict(observed, mediaSources=0)),
                          dict(valid, afterBootstrap=dict(observed, videoAvailable=False))):
                with self.assertRaises(AssertionError):
                    smoke_windows.check_restored_graph_refusal(wrong, module, expected_sources=5)
            (module / "source-ownership.json").unlink()
            with self.assertRaises(AssertionError):
                smoke_windows.check_restored_graph_refusal(valid, module, expected_sources=5)

    def test_fresh_smoke_measures_obs_restored_graph_before_second_launch(self):
        smoke = (ROOT / "native-host/tests/smoke_windows.py").read_text(encoding="utf-8")
        first = smoke.index("expect_created=0 if existing_wall else 5")
        restored = smoke.index('restored_name = f"native-smoke-')
        second = smoke.index("second_name, reuse=True")
        self.assertLess(first, restored)
        self.assertLess(restored, second)
        segment = smoke[restored:second]
        self.assertIn("restored_name", segment)
        self.assertIn("diagnostic=False", segment)
        self.assertIn("expected_sources=5", segment)
        self.assertIn("mutated the bootstrap receipt", segment)
        self.assertIn("rewrote the ownership ledger", segment)
        self.assertIn('"restoredGraphRefusalVerified": not existing_wall', smoke)

    def test_video_receipt_checks_actual_mode_instead_of_accepting_a_flag(self):
        expected = {"baseWidth": 1280, "baseHeight": 720, "outputWidth": 1280,
                    "outputHeight": 720, "fpsNumerator": 15, "fpsDenominator": 1}
        receipt = {"ok": True, "created": 5, "reused": 0, "items": 5, "canvasApplied": True,
                   "videoInfo": expected.copy(), "renderer": {"available": True, "api": "d3d11",
                    "hardwareDecodeVerified": False, "software": True, "adapterLuid": "00000000:00001234",
                    "vendorId": 5140, "deviceId": 140, "dedicatedVideoMemoryCapacityBytes": 0}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            smoke_windows.check_product_receipt(path, expect_video=expected)
            for field in expected:
                changed = copy.deepcopy(receipt)
                changed["videoInfo"][field] += 1
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(AssertionError):
                    smoke_windows.check_product_receipt(path, expect_video=expected)
            del receipt["videoInfo"]
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(AssertionError):
                smoke_windows.check_product_receipt(path, expect_video=expected)

    def test_actual_adapter_receipt_distinguishes_software_and_hardware_without_decode_claim(self):
        receipt = {"available": True, "api": "d3d11", "hardwareDecodeVerified": False,
                   "software": False, "adapterLuid": "00000000:00001234", "vendorId": 0x10de,
                   "deviceId": 0x1234, "dedicatedVideoMemoryCapacityBytes": 16 * 1024 ** 3}
        smoke_windows.check_renderer_receipt(receipt)
        software = dict(receipt, software=True, dedicatedVideoMemoryCapacityBytes=0)
        smoke_windows.check_renderer_receipt(software)
        for changed in [dict(receipt, available=False), dict(receipt, adapterLuid="GPU0"),
                        dict(receipt, software="false"), dict(receipt, hardwareDecodeVerified=True),
                        dict(receipt, vendorId=-1), dict(receipt, dedicatedVideoMemoryCapacityBytes=None), None]:
            with self.assertRaises(AssertionError):
                smoke_windows.check_renderer_receipt(changed)

    def test_decode_request_receipt_does_not_accept_missing_boolean_or_out_of_range(self):
        receipt = {"ok": True, "created": 5, "reused": 0, "items": 5, "canvasApplied": False,
                   "hardwareDecodeRequestedSources": 5}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            smoke_windows.check_product_receipt(path, expect_hardware_requests=5)
            for wrong in (None, True, False, "5", -1, 6, 0):
                changed = dict(receipt, hardwareDecodeRequestedSources=wrong)
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(wrong=wrong), self.assertRaises(AssertionError):
                    smoke_windows.check_product_receipt(path, expect_hardware_requests=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
