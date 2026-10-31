#!/usr/bin/env python3
"""Cross-platform build/isolation tests, not Windows/Qt/media qualification."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
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
    def test_lock_matches_pinned_obs_and_only_needed_dependencies(self):
        lock = json.loads((ROOT / "desktop/dependencies.lock.json").read_text())
        presets = json.loads((ROOT / "obs/obs-studio/CMakePresets.json").read_text())
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
                self.assertEqual((output / "nested with spaces/second.txt").read_text(), "another tracked entry\n")
                receipt = json.loads((output / ".webobs-source.json").read_text())
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
                self.assertEqual((output / "tool-link").read_text(), "../private.txt")
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
            self.assertEqual(json.loads((runtime / "webobs-native-prototype.json").read_text()), manifest)
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
        builder = (ROOT / "desktop/scripts/build-obs-native.ps1").read_text()
        launcher = (SCRIPTS / "launch-native.ps1").read_text()
        for expected in ("-DENABLE_FRONTEND=ON", "-DENABLE_BROWSER=OFF", "-DQt6_DIR=", "-A','x64", "-DCMAKE_SYSTEM_VERSION=10.0.22621.0", "BuildDirectory already exists"):
            self.assertIn(expected, builder)
        for forbidden in ("prepare-obs-headless.py", "Invoke-Checked 'pnpm'", "ENABLE_FRONTEND=OFF", "Invoke-Checked 'node'", "clients/", "GStreamer"):
            # Comment explicitly states no GStreamer; commands must never import it.
            if forbidden != "GStreamer":
                self.assertNotIn(forbidden, builder)
        for expected in ("$AllowPrototype", "--portable", "--disable-updater", "WorkingDirectory = Join-Path $root 'bin/64bit'", "OBS_PLUGINS_PATH", "QT_PLUGIN_PATH", "defaultProduct"):
            self.assertIn(expected, launcher)
        self.assertNotIn("Start-Process", launcher)  # Explicit child environment, fixed CWD.
        self.assertNotIn("--multi", launcher)  # Do not bypass upstream portable instance guard.


if __name__ == "__main__":
    unittest.main(verbosity=2)
