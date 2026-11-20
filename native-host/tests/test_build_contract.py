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
        The gate then compares live helper ports with the ports the host claims and gives
        a retiring Scene graph a bounded grace period, because run 44548882087 lost a PID
        that belonged to a released graph rather than to a mix the host still claimed.
        """
        if os.name == "nt":
            self.skipTest("fake PowerShell needs a POSIX executable")
        spec = importlib.util.spec_from_file_location("product_windows",
            ROOT / "native-host/tests/product_windows.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        gate = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")
        for wiring in ("audio_mix_helper_watch", "mixer_identities(powershell, rows",
                       '"port": helper_port(clean)', "identities.get(pid) or MIXER_IDENTITY_UNAVAILABLE",
                       "assert isinstance(row, dict)", 'return row',
                       'mixers_before_stop["processes"]',
                       "before-program-output-stop", "after-program-output-stop",
                       '"mixerPort": entry.get("mixerPort")', "watched_ports(row)",
                       "claimed_ports(row)", "current_live_ports()",
                       "mix-ports-still-unresolved", "mixerPortSettleMs",
                       "host still reports a live mix", "fixture publishers",
                       "other helpers"):
            self.assertIn(wiring, gate)
        with tempfile.TemporaryDirectory() as temporary:
            fake = Path(temporary) / "pwsh"
            # A real mix helper line is ~509 characters with the loopback target at the
            # end, so the fake one is padded past the recorded cap on purpose: the port
            # has to survive the cap and the tail has to still name the mix target.
            # Placeholder credentials on the TEST-NET documentation range, the form the public
            # repository audit approves for test fixtures: the helper line must still carry a
            # userinfo for the sanitizer assertion to mean anything.
            filler = "-filter_complex amix=inputs=2:duration=longest " + "x" * 240
            fake.write_text("#!/usr/bin/env python3\n"
                "print('12|C:/run/bin/ffmpeg.exe -rtsp_transport tcp -i "
                "rtsp://fixture-user:fixture-password@192.0.2.9:554/tone " + filler + " "
                "-map [amixed] -c:a aac -f mpegts tcp://127.0.0.1:56?listen=1')\n"
                "print('34|C:/run/bin/ffmpeg.exe -i tcp://192.0.2.9:1234/tone ' + 'y'*400)\n"
                "print('not-a-pid|ignored')\n", encoding="utf-8")
            fake.chmod(0o755)
            identities = module.mixer_identities(fake, [12, 34, 99], ("C:/run/bin",))
            self.assertEqual(sorted(identities), [12, 34])
            self.assertIn("<url>", identities[12]["identity"])
            self.assertNotIn("rtsp://", identities[12]["identity"])
            self.assertNotIn("fixture-password", identities[12]["identity"])
            self.assertNotIn("C:/run/bin", identities[12]["identity"])
            # The loopback mix port is the key that ties this helper to its mix source,
            # and it is read before the cap, so a long command line still reports it.
            self.assertGreater(len(identities[12]["identity"]), 120)
            self.assertEqual(len(identities[12]["identity"]), 160)
            self.assertEqual(identities[12]["port"], 56)
            self.assertIn("tcp:56", identities[12]["tail"])
            self.assertNotIn("192.0.2.9", identities[12]["tail"])
            self.assertIn("tcp:56", identities[12]["identity"] + identities[12]["tail"])
            # A remote tcp endpoint stays masked and owns no mix; its tail is recorded so
            # a port-less helper is still explainable, and the cap never leaks the host.
            self.assertIn("<url>", identities[34]["identity"])
            self.assertNotIn("192.0.2.9", identities[34]["identity"])
            self.assertNotIn("192.0.2.9", identities[34]["tail"])
            self.assertIsNone(identities[34]["port"])
            self.assertEqual(len(identities[34]["identity"]), 160)
            self.assertEqual(module.helper_port("tcp:56?listen=1"), 56)
            self.assertIsNone(module.helper_port("ffmpeg -i <private>/a.mkv"))
            self.assertEqual(module.mixer_identities(fake, []), {})
            broken = module.mixer_identities(Path(temporary) / "absent", [7])
            self.assertEqual(broken, {7: dict(module.MIXER_IDENTITY_UNAVAILABLE)})

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
        # Run 44568325933 handed the watch's helper PID list to these helpers and died on
        # `list indices must be integers or slices, not str`, which hid whether any mix was
        # actually starved. A wrong shape now says so in its own words.
        for reader in (module.watched_ports, module.claimed_ports):
            with self.assertRaises(AssertionError) as wrong_shape:
                reader([12, 34])
            self.assertIn("watch row", str(wrong_shape.exception))

    def test_mix_watch_returns_the_recorded_row_so_the_port_chain_can_be_compared(self):
        """Collect, record and compare mix state on one shape, replayed from rc.67's values.

        Run 44568325933 already proved the ports are readable and that the host claimed
        exactly one mix with `mixerPort=51389`, yet the round died on a TypeError because
        the watch handed back the helper PID list and the port comparison then read
        `row["hostClaims"]` off that list. This replays the whole chain - enumerate helpers,
        name them, record the row, compare ports - against the receipt's own shapes, so the
        chain that only ever ran on a Windows runner is checked on Linux too. With the
        pre-fix watch it fails on the returned shape instead of reporting a mix verdict.
        """
        spec = importlib.util.spec_from_file_location("product_windows",
            ROOT / "native-host/tests/product_windows.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")
        node = next(item for item in ast.walk(ast.parse(source))
            if isinstance(item, ast.FunctionDef) and item.name == "audio_mix_helper_watch")
        code = ast.get_source_segment(source, node)
        self.assertIn("def audio_mix_helper_watch", code)
        exec(compile(code, str(ROOT / "native-host/tests/product_windows.py"), "exec"),
            module.__dict__)

        class AlivePublisher:
            def poll(self):
                return None

        helpers = {}

        def identity(port):
            return {"identity": f"C:/<private>/bin/ffmpeg.exe -f mpegts tcp:{port}",
                "tail": f"-c:a aac -f mpegts tcp:{port}", "port": port}

        def fake_child_processes(powershell, pid):
            return [(pid, "ffmpeg.exe") for pid in sorted(helpers)]

        def fake_mixer_identities(powershell, pids, private_values=()):
            return {pid: helpers[pid] for pid in pids}

        claim = [{"sourceId": "fixture-alt-offset.fixture-alt-source", "mixers": 2,
            "processExitCode": -1, "available": True, "active": True, "mixerPort": 51389}]
        module.child_processes = fake_child_processes
        module.mixer_identities = fake_mixer_identities
        module.state = lambda: {"pid": 4321, "audioSources": claim}
        module.rtsp = type("FixtureState", (), {"publishers": [AlivePublisher(), AlivePublisher()]})()
        module.evidence = {}
        module.powershell = "powershell"
        module.private = module.runtime = module.profile = "C:/run/private"
        # rc.67's first sample: one retiring graph still holds port 51078 while the only
        # mix the host claims reads 51389, so nothing the host claims may be starved.
        helpers.update({12: identity(51078), 13: identity(51389)})
        start = module.audio_mix_helper_watch("publish-disconnect-start")
        self.assertIsInstance(start, dict,
            "the watch has to hand back the recorded row, not the helper PID list")
        self.assertIs(module.evidence["audioMixHelperWatch"][-1], start)
        self.assertEqual(module.watched_ports(start), [51078, 51389])
        self.assertEqual(module.claimed_ports(start), [51389])
        self.assertEqual(sorted(set(module.claimed_ports(start)) - set(module.watched_ports(start))),
            [], "a mix the host claims must have a live helper at the first sample")
        self.assertEqual([item["state"] for item in start["fixturePublishers"]], ["alive", "alive"])
        self.assertEqual(start["otherHelpers"], [])
        self.assertTrue(all(item["tail"].endswith("tcp:51078") or item["tail"].endswith("tcp:51389")
            for item in start["processes"]), "the tail has to keep naming the mix target")
        # rc.67's sample after Program output stopped: the retiring graph's helper is gone
        # and the claimed port is still served, which the convergence bar accepts.
        helpers.clear()
        helpers.update({13: identity(51389)})
        after = module.audio_mix_helper_watch("after-program-output-stop")
        self.assertIsInstance(after, dict)
        self.assertEqual(module.watched_ports(after), module.claimed_ports(after))
        self.assertEqual(module.claimed_ports(after), [51389])
        self.assertEqual(module.watched_ports(after), [51389])
        # A claimed port that loses its helper must still read as an unserved mix, so the
        # convergence verdict is not just the happy path of this replay.
        helpers.clear()
        helpers.update({13: identity(51078)})
        starved = module.audio_mix_helper_watch("mix-ports-still-unresolved")
        self.assertEqual(sorted(set(module.claimed_ports(starved)) - set(module.watched_ports(starved))),
            [51389], "a claimed port without a live helper has to be reported as unserved")

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

    def test_the_installed_soak_gate_repairs_its_own_feed_before_blaming_the_product(self):
        """Replay the two-hour watch on Linux: harness faults and product faults differ.

        This gate only ever runs on a Windows runner, and it is the last thing between a
        passing candidate and a publishable freeze, so it is replayed here with a fake
        host and fake fixture publishers. A publisher that exits while looping a fixture
        file is the harness's own fault: the watch must restart it and keep watching, and
        must not report a product stall (commit 1861627). A stalled input, a process tree
        that changed while nothing but watching happened, private memory or handle growth
        past the bound, an unreadable process and an idle tree all still fail, and the
        receipt has to carry the per-minute readings.
        """
        spec = importlib.util.spec_from_file_location("product_windows",
            ROOT / "native-host/tests/product_windows.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")
        node = next(item for item in ast.walk(ast.parse(source))
            if isinstance(item, ast.FunctionDef) and item.name == "soak_watched_inputs")
        code = ast.get_source_segment(source, node)
        self.assertIn("def soak_watched_inputs", code)
        exec(compile(code, str(ROOT / "native-host/tests/product_windows.py"), "exec"),
            module.__dict__)

        class FakeTime:
            def __init__(self):
                self.now = 0.0
            def monotonic(self):
                return self.now
            def sleep(self, seconds):
                self.now += seconds

        class Publisher:
            """Fake fixture publisher: alive, or exited from `dies_at` simulated seconds on."""

            def __init__(self, clock, alive=True, dies_at=None):
                self.clock = clock
                self.alive = alive
                self.dies_at = dies_at
                self.restarted = 0
            def poll(self):
                if self.dies_at is not None and self.clock.now >= self.dies_at:
                    return 1
                return None if self.alive else 1

        def run(minutes, *, metrics, stalled_minutes=(), dead_minutes=()):
            clock = FakeTime()
            # dead_minutes names the simulated minute (0-based) in which the second
            # fixture publisher exits; that one, and only that one, must be restarted.
            died_in = dead_minutes[0] if dead_minutes else None
            publishers = [Publisher(clock), Publisher(clock, dies_at=None if died_in is None else died_in * 60)]
            module.rtsp = type("FixtureRtsp", (), {
                "publishers": publishers,
                "server": Publisher(clock),
                "restart_publisher": lambda self, index: (
                    setattr(publishers[index], "alive", True),
                    setattr(publishers[index], "dies_at", None),
                    setattr(publishers[index], "restarted", publishers[index].restarted + 1))})()
            module.time = clock
            module.evidence = {"checks": []}
            module.checkpoint = lambda name: None
            samples = list(metrics)
            module.process_tree_metrics = lambda: dict(samples.pop(0))
            # The gate always asks "are zero inputs stalled"; the fake answers that from the
            # simulated clock so a chosen minute can report a frozen input.
            module.ui = lambda action, **fields: int(clock.now // 60) not in stalled_minutes
            module.soak_watched_inputs(minutes)
            return publishers

        def tree(cpu, private=500_000_000, handles=300, pids=(10, 11, 12), unavailable=()):
            return {"cpuSeconds": cpu, "privateBytes": private, "handles": handles,
                "processIds": list(pids), "unavailable": list(unavailable)}

        healthy = run(3, metrics=[tree(0.0), tree(60.0), tree(120.0)])
        self.assertEqual([publisher.restarted for publisher in healthy], [0, 0])
        self.assertEqual(module.evidence["soak"]["minutes"], 3)
        self.assertEqual(module.evidence["soak"]["intervalSeconds"], 60)
        self.assertEqual(len(module.evidence["soak"]["samples"]), 3)
        self.assertEqual(module.evidence["soak"]["cpuSecondsDelta"], 120.0)
        self.assertIn("installed-soak-3-minutes-five-inputs", module.evidence["checks"])

        repaired = run(3, dead_minutes=(1,), metrics=[tree(0.0), tree(60.0), tree(120.0)])
        self.assertEqual([publisher.restarted for publisher in repaired], [0, 1],
            "the minute whose publisher exited must have that publisher restarted")
        self.assertEqual(module.evidence["fixturePublisherWatch"][0]["dead"], [1])
        self.assertIn("installed-soak-3-minutes-five-inputs", module.evidence["checks"],
            "a repaired fixture feed is a harness fault, not a product stall")

        with self.assertRaisesRegex(AssertionError, "soak minute 2"):
            run(3, metrics=[tree(0.0), tree(60.0), tree(120.0)], stalled_minutes=(1,))
        with self.assertRaisesRegex(AssertionError, "process tree changed"):
            run(3, metrics=[tree(0.0, pids=(10, 11)), tree(60.0, pids=(10, 11, 12)),
                tree(120.0, pids=(10, 11, 12))])
        with self.assertRaisesRegex(AssertionError, "private memory grew"):
            run(3, metrics=[tree(0.0), tree(60.0), tree(120.0, private=820_000_000)])
        with self.assertRaisesRegex(AssertionError, "handle count grew"):
            run(3, metrics=[tree(0.0), tree(60.0), tree(120.0, handles=520)])
        with self.assertRaisesRegex(AssertionError, "could not read every product process"):
            run(3, metrics=[tree(0.0, unavailable=(11,)), tree(60.0), tree(120.0)])
        with self.assertRaisesRegex(AssertionError, "used only"):
            run(3, metrics=[tree(0.0), tree(1.0), tree(2.0)])
        # A publisher exiting inside the window is repaired; the loopback server itself
        # dying is not the product's fault either, but it does invalidate the window.
        module.rtsp = type("FixtureRtsp", (), {"publishers": [Publisher(FakeTime())],
            "server": Publisher(FakeTime(), alive=False),
            "restart_publisher": lambda self, index: None})()
        module.evidence = {"checks": []}
        module.process_tree_metrics = lambda: tree(0.0)
        module.ui = lambda action, **fields: True
        with self.assertRaisesRegex(AssertionError, "loopback RTSP server exited"):
            module.soak_watched_inputs(1)

    def test_the_gain_control_step_records_its_measurement_before_rejecting_it(self):
        """A rejected Program control step still has to say what it measured.

        Run 44577184643 failed its unchanged-gain control step and the receipt that
        arrived carried only the two ratios. The reference amplitudes, the window each
        was taken in and the per-segment readings behind them were written to the
        evidence AFTER the assertion, so the next session had nothing to re-check. This
        fixes the order of the statements, not the thresholds: the control step keeps
        its 0.8-1.25 bound, the gain bounds stay as written, and the amplitude comes
        from the shared measurement rule in pixel_windows rather than a local copy.
        """
        gate = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")
        record = gate.index('evidence["programTrackGain"] = {')
        reject = gate.index("measured differently twice")
        self.assertLess(record, reject,
            "the gain control step must record its measurement before rejecting it")
        self.assertLess(gate.index('evidence["programTrackGain"].update('),
            gate.index("did not scale the second track"),
            "the reduced-gain reading has to be recorded before it is judged")
        for wiring in ('"toneReadings"', '"steadyWindowStarts"', '"controlRatios"',
                       '"reducedToneReadings"'):
            self.assertIn(wiring, gate)
        for bound in ("0.8 <= ratio <= 1.25", "0.05 < gain_low_880 / gain_full_880 < 0.55",
                      "0.6 < gain_low_440 / gain_full_440 < 1.5",
                      "muted_440 > 200 and muted_880 < 60"):
            self.assertIn(bound, gate, "the Program audio acceptance bound changed")
        # The amplitude rule lives in one place, so a Windows gate and a local FFmpeg
        # fixture measure the same thing.
        self.assertNotIn("def _correlate(", gate)
        self.assertIn("pixel_windows.steady_tone_window", gate)


    def test_the_publish_toggle_says_why_the_owned_window_was_unusable(self):
        """Run 44587525224: the resume toggle failed with an empty AssertionError.

        ui() answers False in two different situations - this boot's own state
        observation was unusable, or UI Automation refused the owned window - and a bare
        ``assert ui(...)`` reported neither, so the installed gate stopped at
        ``program-publish-disconnect`` with detail ``AssertionError: ``. ui_control waits
        only for the addressability case and records every reason; a real UI Automation
        refusal is not retried, because the click never landed, and failure_detail only
        appends the recorded verdict to an assert that had no message of its own. The
        publish acceptance itself is unchanged.
        """
        source = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")
        lines = source.splitlines()
        start = next(index for index, line in enumerate(lines, 1)
                     if 'phase = "program-publish-disconnect"' in line)
        end = next(index for index, line in enumerate(lines, 1)
                   if "restarted publisher never delivered frames again" in line)
        tree = ast.parse(source)
        bare = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)
            and isinstance(node.test, ast.Call) and getattr(node.test.func, "id", "") == "ui"
            and start <= node.lineno <= end]
        self.assertEqual(bare, [], "a publish toggle still has an unexplained bare assert")
        self.assertEqual(source.count('ui_control("stream-program"'), 2,
            "both publish toggles of the relay-loss probe have to record their reason")
        for wiring in ('"lastUiUnavailable"', '"lastStateObservation"', '"productControlWaits"',
                       "def window_owner"):
            self.assertIn(wiring, source)
        # Both refusal paths record the handle verdict, so a UI Automation refusal cannot
        # read like a startup wait any more (run 44599567300 said only product-window).
        self.assertEqual(source.count('"reportedHandles"'), 2,
            "the unusable-window path and the UI Automation refusal path both have to name the handle verdict")
        ui_automation = (ROOT / "native-host/tests/product-ui.ps1").read_text(encoding="utf-8")
        gone, mismatch = ui_automation.index("'window-handle-gone'"), ui_automation.index("'window-pid-mismatch'")
        self.assertLess(gone, ui_automation.index("Invoke-Control"),
            "the UI Automation helper reports why the owned window was refused before touching any control")
        self.assertLess(mismatch, ui_automation.index("Invoke-Control"))
        self.assertLess(ui_automation.index("Start-Sleep -Milliseconds 400"), gone,
            "a handle that is being recreated is re-asked before it is reported gone")

        spec = importlib.util.spec_from_file_location("product_windows",
            ROOT / "native-host/tests/product_windows.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        node = next(item for item in ast.walk(ast.parse(source))
            if isinstance(item, ast.FunctionDef) and item.name == "ui_control")
        exec(compile(ast.get_source_segment(source, node), str(ROOT / "native-host/tests/product_windows.py"),
            "exec"), module.__dict__)

        class FakeTime:
            def __init__(self):
                self.now = 0.0
            def monotonic(self):
                return self.now
            def sleep(self, seconds):
                self.now += seconds

        def run(ui_results, *, unavailable=None, refusal=None, timeout=15):
            module.time = FakeTime()
            module.evidence = {}
            # The product's own UI-thread account, as the state observation publishes it.
            module.state = lambda: {"uiStallMs": 6100, "uiStallMaxMs": 6100,
                "uiStallAtMs": 1700000000600, "publishedAtMs": 1700000000700,
                "programOutput": {"teardown": {"relayStopMs": 6000, "relayStopMaxMs": 6000,
                    "publishReleaseMs": 120, "publishReleaseMaxMs": 120,
                    "publishStopWaitMs": 40, "publishStopWaitMaxMs": 40}}}
            if refusal is not None:
                module.evidence["lastUiFailure"] = refusal
            seen = []
            outcomes = list(ui_results)

            def fake_ui(action, **fields):
                seen.append(action)
                passed = outcomes.pop(0)
                # Only a failed call leaves a reason behind, exactly as ui() does.
                if passed:
                    module.evidence.pop("lastUiUnavailable", None)
                elif unavailable is not None:
                    module.evidence["lastUiUnavailable"] = unavailable
                return passed
            module.ui = fake_ui
            return module.ui_control("stream-program", label="publish again after a relay loss",
                timeout=timeout), seen

        recovered, calls = run([False, False, True], unavailable={"stage": "stream-program",
            "code": "owned-window-unavailable", "matchedWindows": 0, "reportedHandles": ["gone"],
            "stateObservation": {"code": "state-file-unreadable"}})
        self.assertTrue(recovered)
        self.assertEqual(calls, ["stream-program", "stream-program", "stream-program"])
        self.assertEqual(module.evidence["productControlWaits"][-1]["recoveredAfterAttempts"], 2)
        self.assertEqual(module.evidence["productControlWaits"][-1]["unusableAttempts"][0]["code"],
            "owned-window-unavailable")
        self.assertEqual(module.evidence["productControlWaits"][-1]["uiThread"]["uiStallMaxMs"], 6100,
            "a control that needed waits still has to say how long the UI thread was held")
        self.assertEqual(module.evidence["productControlWaits"][-1]["uiThread"]["teardown"]["relayStopMs"], 6000)
        self.assertNotIn("lastUiUnavailable", module.evidence)

        refused, calls = run([False], unavailable=None, refusal={"stage": "initialize",
            "code": "product-window"})
        self.assertFalse(refused, "a UI Automation refusal must not be retried or hidden")
        self.assertEqual(calls, ["stream-program"], "a refusal means the click never landed, so retrying would double it")
        self.assertIsNone(module.evidence["productControlWaits"][-1]["lastUnavailable"])
        self.assertEqual(module.evidence["productControlWaits"][-1]["lastUiFailure"]["code"], "product-window")
        refusal_wait = module.evidence["productControlWaits"][-1]["uiThread"]
        self.assertEqual(refusal_wait["uiStallAtMs"], 1700000000600,
            "the refusal has to carry when the product's own heartbeat last came back late")
        self.assertEqual(refusal_wait["teardown"]["publishReleaseMaxMs"], 120,
            "the refusal has to carry the Program teardown durations behind it")

        never, calls = run([False] * 40, unavailable={"stage": "stream-program",
            "code": "owned-window-unavailable", "matchedWindows": 0, "reportedHandles": ["gone"]},
            timeout=6)
        self.assertFalse(never, "a window that stays unusable still fails the gate")
        self.assertGreater(len(calls), 1)
        self.assertLessEqual(len(module.evidence["productControlWaits"][-1]["unusableAttempts"]), 4)
        self.assertEqual(module.evidence["productControlWaits"][-1]["recoveredAfterAttempts"], 0)

        empty = module.failure_detail(AssertionError(""), {"lastUiUnavailable":
            {"stage": "stream-program", "code": "owned-window-unavailable",
             "reportedHandles": ["gone", "other-process(4321)"]}})
        self.assertIn("owned-window-unavailable", empty)
        self.assertIn("gone", empty)
        self.assertEqual(module.failure_detail(AssertionError("publish control could not resume"),
            {"lastUiUnavailable": {"code": "owned-window-unavailable"}}),
            "AssertionError: publish control could not resume",
            "an assertion that already explains itself must not be rewritten")


    def test_publish_control_refusal_names_the_ui_thread_owner(self):
        """A refused Program control has to say whether the product held its own UI thread.

        Runs 44587525224 and 44599567300 refused the resume toggle after a relay loss with
        one shared UI Automation code, which cannot separate a window the product destroyed
        from a UI thread the product is holding inside a Program teardown. The host now
        measures its own late heartbeat ticks and every Program teardown duration, and the
        gate records both beside the refusal so the next round names the layer instead of
        guessing it.
        """
        output = (ROOT / "native-host/src/product_output.cpp").read_text(encoding="utf-8")
        header = (ROOT / "native-host/src/product_output.hpp").read_text(encoding="utf-8")
        window = (ROOT / "native-host/src/product_window.cpp").read_text(encoding="utf-8")
        gate = (ROOT / "native-host/tests/product_windows.py").read_text(encoding="utf-8")

        self.assertIn("struct TeardownSpan", output)
        for span in ("TeardownSpan span(relay_stop_last_ms, relay_stop_max_ms);",
                     "TeardownSpan span(publish_release_last_ms, publish_release_max_ms);",
                     "TeardownSpan span(publish_stop_wait_last_ms, publish_stop_wait_max_ms);"):
            self.assertIn(span, output, "every Program teardown the UI thread waits for must be measured")
        for field in ("relay_stop_last_ms", "publish_release_last_ms", "publish_stop_wait_max_ms"):
            self.assertIn(field, header)
            self.assertIn("value.%s = impl_->%s;" % (field, field), output)
        # The private state observation is the only channel the installed gate can read.
        for key in ("uiStallMs", "uiStallMaxMs", "uiStallAtMs", "teardown"):
            self.assertIn('"%s"' % key, window)
        self.assertIn("now_ms - heartbeat_last_ms_ - heartbeat_interval_ms", window)
        self.assertIn("def ui_thread_snapshot", gate)
        self.assertEqual(gate.count('"uiThread": ui_thread_snapshot()'), 2,
            "both the refusal and a control that needed waits carry the product's own account")

    def test_the_first_installed_start_waits_for_this_boot_host_state(self):
        """Run 44609775780: the restored-pair first start sampled the host state too early.

        The supervisor publishes native-status.json with ``phase=running`` right after it
        spawns ``obs64.exe`` (product_supervisor.py calls ``status("running")`` immediately
        after the frontend Popen), while the host writes product-state.json only once libobs
        has loaded the product module and bound its session, carrying this boot's pid and
        bootId. rc.71 passed the portable and installed gates 77 checks each and then failed
        the interrupted-restore-pair-recovery phase with "the running host did not publish
        one product state", because the gate sampled the observation on the same tick the
        entry reported running - the file simply was not written yet. The gate has to wait
        for exactly one readable state file owned by this boot inside the original 120 s
        launch budget, and its receipt has to distinguish zero files, several files, an
        unreadable file and an observation from an older boot. Convergence, dual-directory
        consistency, rollback retention and process-cleanup assertions stay immediate: a
        journal, a half pair or a surviving process is a product defect at that instant.
        运行 44609775780：恢复成对档案后的首次启动采样宿主状态太早。supervisor 在 Popen
        前端后立即写 native-status.json 的 running，宿主模块加载并绑定会话后才写带本次
        PID/bootId 的 product-state.json；门禁必须在原 120 秒启动预算内等到恰好一份属于
        本次启动的可读状态文件，并在回执区分零份、多份、不可读与旧启动文件。
        """
        source = (ROOT / "native-host/tests/backup_restore_windows.py").read_text(encoding="utf-8")
        self.assertNotIn("assert len(state_paths) == 1", source,
            "the host state must be awaited, not sampled at the instant the entry reported running")
        for classification in ('"state-file-count"', '"state-file-unreadable"', '"state-from-other-boot"',
                               '"pidMatched"', '"bootIdMatched"'):
            self.assertIn(classification, source,
                "the receipt must name which state-file outcome the bounded wait saw")
        self.assertRegex(source, r"launch_deadline\s*=\s*time\.monotonic\(\)\s*\+\s*120",
            "one 120 s launch budget computed before the entry starts governs this phase")
        tree = ast.parse(source)
        budgeted_waits = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "wait_for" and any(
                kw.arg == "timeout" and getattr(kw.value.func, "id", "") == "remaining"
                for kw in node.keywords if kw.arg == "timeout" and isinstance(kw.value, ast.Call))
            )
        self.assertGreaterEqual(budgeted_waits, 2,
            "both the running-status wait and the host-state wait consume the same launch budget")
        self.assertIn('service.get("name") == "frontend"', source,
            "the state file must match the frontend child of this boot, not any obs process")
        self.assertIn('value.get("bootId") != started["bootId"]', source,
            "an observation left by a previous boot must be rejected as stale")
        for preserved in ("the installed entry left the interrupted restore journal behind",
                          "the installed entry never landed the pending OBS profile half",
                          "the installed entry recorded a bounded recovery failure instead of converging",
                          "the installed entry started without the restored configuration",
                          "the installed entry started on a mismatched OBS profile half",
                          "the installed entry deleted the previous pair instead of keeping it retryable",
                          "the interrupted-restore first start left its own product processes alive"):
            self.assertIn(preserved, source, "convergence, consistency, retention or cleanup lost its assert")

    def test_the_native_swap_kill_follows_the_recorded_journal(self):
        """Run 44711476489: the native-swap sentinel fired before nativeRollback was persisted.

        rc.72 cleared the rc.71 host-state race and then failed "journal does not record
        both previous halves": the interrupt-native hook paused inside ``os.replace`` after
        the previous OBS profile had physically moved aside, but ``encrypted_backup.py``
        records ``nativeRollback`` only once that call returns, so the kill happened in the
        microsecond window between the swap and its fsync'ed journal write. A crash there
        is a genuine loss of the native reference, not the prepared-state window the
        recovery design promises; the sentinel must therefore follow the ``_write_journal``
        call that persists both halves, while the configuration half still has not landed.
        The same run also showed a failing assert leaving the sleeping child on its log:
        cleanup then raised WinError 32 and hid the assertion, so both interruption phases
        terminate their child and close the log in ``finally``. Product recovery stays
        untouched - it rolls the pair back exactly as ``recover_interrupted`` documents.
        运行 44711476489：原生半区哨兵在 journal 落盘前触发。rc.72 修好宿主状态竞态后停在
        "journal does not record both previous halves"：interrupt-native 钩子在上一次 OBS
        档案物理移开后、os.replace 尚未返回时暂停，而 encrypted_backup.py 要到调用返回才
        fsync 记录 nativeRollback，杀进程落在交换与 journal 写入之间的微秒窗口，真正丢失
        原生半区引用，并非产品承诺的可恢复 prepared 状态。哨兵必须跟在记录两份前像的
        _write_journal 之后、配置半区落盘之前；两个中断阶段也都要在 finally 里终止子进程
        并关闭日志，避免断言失败被 WinError 32 掩盖。产品恢复逻辑不改。
        """
        source = (ROOT / "native-host/tests/backup_restore_windows.py").read_text(encoding="utf-8")
        self.assertIn("module._write_journal = guarded_journal", source,
            "the native-swap window must be taken after the journal write, not inside os.replace")
        self.assertIn('value.get("nativeRollback") is None', source,
            "the guard must only stop the child once both previous halves are recorded")
        self.assertNotIn('sentinel.write_text("native-swapped-out"', source,
            "the sentinel fired while nativeRollback was still only in memory")
        child = source.split('CHILD = """', 1)[1].split('"""', 1)[0]
        self.assertLess(child.index("write_journal(path, value)"),
            child.index('sentinel.write_text("native-recorded"'),
            "the sentinel must follow the fsync'ed journal write")
        tree = ast.parse(source)
        guarded_children = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and node.finalbody and any(
                isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "kill" for call in ast.walk(ast.Module(body=node.finalbody, type_ignores=[]))):
                guarded_children += 1
        self.assertGreaterEqual(guarded_children, 2,
            "both interruption phases must terminate their child in finally so cleanup cannot hide the assert")
        for preserved in ("journal does not record both previous halves",
                          "one half was still live while the journal claims both were swapped out",
                          "the installed entry did not return both halves of the previous pair",
                          "the installed entry left the previous OBS profile parked",
                          "the previous OBS profile stayed parked instead of becoming live again"):
            self.assertIn(preserved, source, "the native-swap rollback asserts must stay verbatim")

    def test_the_second_installed_start_waits_for_its_own_boot_status(self):
        """Run 44718717601: the second start accepted the killed first boot's status file.

        rc.73 moved the native-swap sentinel after the journal write, so the paired
        restore advanced to the second installed start. The first instance was killed
        there and its native-status.json stayed on disk with phase=running and a valid
        32-hex bootId: the supervisor never deletes that file when terminated, and it
        publishes a fresh per-boot bootId only after prepare() has already run
        recover_interrupted_restore(). wait_for polled after 100 ms, accepted the
        previous boot's file, and the convergence assert reported that the installed
        entry left the native-swap journal behind while this boot had not converged
        anything yet - the journal really was still there, just not yet observed by
        the right start. The wait must capture the boot id standing before the entry
        launches and reject it, naming the outcome the bounded wait saw; the journal,
        marker and staging asserts stay immediate. Product ordering is unchanged:
        recovery still precedes directory creation and the first status publish.
        运行 44718717601：第二次启动接受了被终止的第一次启动遗留的状态文件。rc.73 把原生
        半区哨兵挪到 journal 落盘之后，成对恢复推进到第二次安装态启动：第一次实例在那里被
        终止，它的 native-status.json 仍留在磁盘上（phase=running、bootId 是合法 32 位
        十六进制），supervisor 被终止时不会删除该文件，而新 bootId 要到 prepare() 完成
        recover_interrupted_restore() 之后才发布；wait_for 第一个 tick（100 ms）就接受了
        旧启动的文件，收敛断言在第二次启动尚未收敛任何东西时报 "journal left behind"——
        journal 确实还在，只是还没被正确的启动观察到。等待必须先记录启动前的 bootId 并拒绝
        它，并记下有界等待看到的判定；journal、marker 与暂存断言保持即时。产品顺序不变：
        恢复仍先于目录创建与状态发布。
        """
        source = (ROOT / "native-host/tests/backup_restore_windows.py").read_text(encoding="utf-8")
        self.assertIn('previous_boot = status().get("bootId")', source,
            "the second start must capture the previous boot before launching the entry")
        self.assertIn("boot_id == previous_boot", source,
            "the previous boot's running status must be rejected as stale")
        for classification in ('"status-not-running"', '"status-from-previous-boot"',
                               '"status-published"', '"previousBootId"'):
            self.assertIn(classification, source,
                "the receipt must name which status outcome the second-start wait saw")
        self.assertEqual(len(source.split("subprocess.Popen([str(entry)")), 4,
            "the gate launches the installed entry three times")
        second_phase = source.index('phase = "second-installed-start"')
        second_launch = source.index("subprocess.Popen([str(entry)", second_phase)
        self.assertLess(source.index('previous_boot = status().get("bootId")', second_phase),
            second_launch,
            "the previous boot must be captured before the second entry launches")
        self.assertIn("wait_for(native_rolled_back, lambda:", source,
            "the stale-status attribution is assembled at timeout, not eagerly")
        for preserved in ("the installed entry did not return both halves of the previous pair",
                          "the installed entry left the native-swap journal behind",
                          "the installed entry did not restore the previous configuration half",
                          "the installed entry left the previous OBS profile parked"):
            self.assertIn(preserved, source, "the native-swap rollback asserts must stay verbatim")

    def test_the_refused_paired_restore_is_charged_only_for_its_own_staging(self):
        """Run 44728029615: the refusal assert charged the staging left by the killed restores.

        rc.74 advanced past the second installed start and failed at
        "the refused paired restore leaked staging directories". restore() converges
        any earlier interruption first and only then refuses a paired archive whose
        caller omits the OBS profile, raising BackupError inside its own
        .webobs-decrypt- TemporaryDirectory, so the refusal cannot leak a directory.
        The two restores killed mid-swap earlier in this gate exit through
        TerminateProcess, which skips context-manager cleanup, and recover_interrupted()
        removes only the staging the journal names - the untracked plaintext decrypt
        directory survives every recovery. The gate must snapshot the staging names
        standing before the refusal, charge only directories the refusal created, and
        disclose the stale leftovers in the receipt; whether the product should sweep
        untracked decrypt staging after a hard kill is crash-recovery design and stays
        with the Codex main thread. A Linux repro against backup/encrypted_backup.py
        confirms the refusal creates no new staging while killed leftovers persist.
        运行 44728029615：拒绝对账把被杀恢复遗留的暂存算到了拒绝本身。rc.74 越过第二次安装态
        启动后在 "the refused paired restore leaked staging directories" 失败。restore()
        先收敛此前的中断，之后才拒绝未指明 OBS 档案的成对档案，并在自己的 .webobs-decrypt-
        TemporaryDirectory 内抛出 BackupError，因此拒绝本身不可能泄漏目录。门禁中此前两次被
        硬终止的恢复经 TerminateProcess 退出，跳过上下文管理器清理，而 recover_interrupted()
        只删除 journal 记录的暂存——未被记录的明文解密暂存会在每次恢复后留存。门禁必须先记录
        拒绝前的暂存名单、只对拒绝新创建的目录记账，并在回执里披露遗留的明文暂存；产品是否
        应在硬终止后清扫未记录的解密暂存属崩溃恢复算法设计，留给 Codex 主线程。对
        backup/encrypted_backup.py 的 Linux 复现确认拒绝不产生新暂存、被杀恢复的遗留仍在。
        """
        source = (ROOT / "native-host/tests/backup_restore_windows.py").read_text(encoding="utf-8")
        refusal_phase = source.index('phase = "legacy-config-only-archive"')
        refusal_launch = source.index('private / "unused-paired-sentinel.txt"', refusal_phase)
        self.assertLess(source.index("stale_staging = sorted(staging_names())", refusal_phase),
            refusal_launch,
            "the staging baseline must be captured before the refused restore runs")
        self.assertIn("staging_names() - set(stale_staging)", source,
            "only staging created by the refusal itself may be charged")
        self.assertIn('evidence["staleStagingFromKilledRestores"]', source,
            "the stale plaintext staging of the killed restores must be disclosed in the receipt")
        for preserved in ("the refused paired restore leaked staging directories",
                          "a paired archive was half-restored without naming the OBS profile",
                          "the refused paired restore still changed one half of the pair",
                          "the refused paired restore left a journal behind"):
            self.assertIn(preserved, source, "the paired-refusal asserts must stay verbatim")


if __name__ == "__main__":
    unittest.main(verbosity=2)
